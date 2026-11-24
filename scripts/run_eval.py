"""对比评测：朴素 RAG 基线 vs CRAG Agent。

流程：加载 data/eval/questions.json → 每题分别跑两条链路 →
DeepSeek 做 LLM Judge 按 judge_points 打分（0 / 0.5 / 1）→ 输出对比表。

用法：.venv/Scripts/python.exe scripts/run_eval.py [--limit N] [--out report.md]
注意：需要先在 .env 中配置 DEEPSEEK_API_KEY，并完成语料入库（scripts/ingest_corpus.py）。
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import ROOT_DIR, settings  # noqa: E402
from app.agent.graph import graph  # noqa: E402
from app.llm import chat, MissingAPIKeyError  # noqa: E402
from app.rag.baseline import naive_rag  # noqa: E402

JUDGE_SYSTEM = """你是问答质量评分器。根据「参考答案要点」给「系统回答」打分（满分 1 分）：
- 1.0：要点全部覆盖且无事实错误
- 0.5：覆盖部分要点，或冗余但无错误
- 0.0：要点未覆盖、答案错误、或对可答问题谎称不知道
输出 JSON：{"score": 0 或 0.5 或 1, "reason": "一句话理由"}"""

INITIAL = {"rewrite_round": 0, "regen_round": 0, "used_web": False, "trace": [], "history": []}


def run_agent(question: str) -> str:
    final = graph.invoke({**INITIAL, "question": question}, config={"recursion_limit": 30})
    return final.get("answer", "")


def judge(question: str, points: str, answer: str) -> tuple[float, str]:
    try:
        out = chat(
            [
                {"role": "system", "content": JUDGE_SYSTEM},
                {"role": "user", "content": f"用户问题：{question}\n\n参考答案要点：{points}\n\n系统回答：\n{answer}"},
            ],
            json_mode=True,
        )
        data = json.loads(out)
        return float(data.get("score", 0)), data.get("reason", "")
    except Exception as exc:
        return 0.0, f"评分失败: {exc}"


def keyword_hit(answer: str, keywords: list[str]) -> float:
    if not keywords:
        return -1.0  # 不适用
    hits = sum(1 for k in keywords if k in answer)
    return hits / len(keywords)


def main() -> None:
    if not settings.api_key_configured:
        print("❌ 尚未配置 DEEPSEEK_API_KEY，请先编辑 .env 填入后再运行评测。")
        sys.exit(1)

    limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else None
    qa = json.loads((ROOT_DIR / "data/eval/questions.json").read_text(encoding="utf-8"))
    questions = qa["questions"][:limit] if limit else qa["questions"]

    rows = []
    for q in questions:
        print(f"[{q['id']}] {q['question'][:30]}…", flush=True)

        # 朴素 RAG
        try:
            naive_ans = naive_rag(q["question"])["answer"]
        except Exception as exc:
            naive_ans = f"(执行失败: {exc})"
        naive_score, naive_reason = judge(q["question"], q["llm_judge_points"], naive_ans)
        naive_kw = keyword_hit(naive_ans, q["expected_keywords"])

        # Agentic RAG
        try:
            agent_ans = run_agent(q["question"])
        except Exception as exc:
            agent_ans = f"(执行失败: {exc})"
        agent_score, agent_reason = judge(q["question"], q["llm_judge_points"], agent_ans)
        agent_kw = keyword_hit(agent_ans, q["expected_keywords"])

        rows.append(
            {
                "id": q["id"],
                "type": q["type"],
                "question": q["question"],
                "naive_score": naive_score,
                "naive_kw": naive_kw,
                "agent_score": agent_score,
                "agent_kw": agent_kw,
                "naive_ans": naive_ans,
                "agent_ans": agent_ans,
                "agent_reason": agent_reason,
            }
        )

    # ---------- 输出 ----------
    def avg(key, rtype=None):
        vals = [r[key] for r in rows if (rtype is None or r["type"] == rtype) and r[key] >= 0]
        return sum(vals) / len(vals) if vals else -1

    lines = [
        "# Agentic RAG 评测报告\n",
        f"评测题数：{len(rows)}　评测模型：{settings.deepseek_model}\n",
        "## 总体对比\n",
        "| 链路 | LLM Judge 平均分 | 关键词命中率 |\n|---|---|---|",
        f"| 朴素 RAG | {avg('naive_score'):.2f} | {avg('naive_kw') * 100:.0f}% |",
        f"| CRAG Agent | {avg('agent_score'):.2f} | {avg('agent_kw') * 100:.0f}% |",
        "\n## 分类型对比\n",
        "| 类型 | 朴素 RAG | CRAG Agent |\n|---|---|---|",
    ]
    for rtype in sorted({r["type"] for r in rows}):
        lines.append(f"| {rtype} | {avg('naive_score', rtype):.2f} | {avg('agent_score', rtype):.2f} |")

    lines += ["\n## 逐题明细\n", "| 题目 | 类型 | 朴素分 | Agent 分 | Agent 评审意见 |\n|---|---|---|---|---|"]
    for r in rows:
        q_short = r["question"][:24] + ("…" if len(r["question"]) > 24 else "")
        lines.append(f"| {r['id']} {q_short} | {r['type']} | {r['naive_score']} | {r['agent_score']} | {r['agent_reason'][:60]} |")

    report = "\n".join(lines)
    print("\n" + report)

    out_path = Path(__file__).resolve().parents[1] / "data" / "eval" / "report.md"
    out_path.write_text(report, encoding="utf-8")
    print(f"\n报告已保存：{out_path}")


if __name__ == "__main__":
    try:
        main()
    except MissingAPIKeyError as exc:
        print(f"❌ {exc}")
        sys.exit(1)
