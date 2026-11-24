"""Agent 各节点实现：路由 → 检索 → 打分 → (改写/联网) → 生成 → 自检 → 完成。

约定：
- 每个节点只返回「状态增量」；trace 事件为新增片段（state 中用 operator.add 归并）
- trace 事件结构：{"step", "label", "status", "detail", "duration_ms"}
- LLM 单点故障不中断流程：路由失败默认走 kb，打分失败默认全部保留
"""
import time

from app.agent.prompts import (
    CHECK_SYSTEM,
    DIRECT_CHAT_SYSTEM,
    GENERATE_SYSTEM,
    GRADE_SYSTEM,
    REGENERATE_SUFFIX,
    REWRITE_SYSTEM,
    ROUTE_SYSTEM,
)
from app.config import settings
from app.llm import MissingAPIKeyError, chat, chat_json, chat_stream
from app.rag import store
from app.rag.baseline import format_context


def _get_writer():
    """取 LangGraph 自定义流写入器（不可用时返回 None，降级为非流式）。"""
    try:
        from langgraph.config import get_stream_writer

        return get_stream_writer()
    except Exception:
        return None


def _stream_llm(messages: list[dict], writer) -> str:
    """流式生成并把 token 实时转发给前端；异常时回退非流式调用。"""
    if writer:
        writer({"type": "answer_reset"})  # 通知前端清空当前答案气泡（重生成场景）
    parts: list[str] = []
    try:
        for piece in chat_stream(messages):
            parts.append(piece)
            if writer:
                writer({"type": "token", "text": piece})
        return "".join(parts).strip()
    except MissingAPIKeyError:
        raise
    except Exception:
        return chat(messages).strip()


def _ev(step: str, label: str, detail: str, started: float, status: str = "done") -> dict:
    return {
        "step": step,
        "label": label,
        "status": status,
        "detail": detail,
        "duration_ms": int((time.perf_counter() - started) * 1000),
    }


def _truncate(text: str, limit: int = 350) -> str:
    return text if len(text) <= limit else text[:limit] + "…"


# ---------------------------------------------------------------- 路由
def route_node(state: dict) -> dict:
    t0 = time.perf_counter()
    question = state["question"]
    route, reason = "kb", "默认走知识库"
    try:
        out = chat_json(
            [
                {"role": "system", "content": ROUTE_SYSTEM},
                {"role": "user", "content": question},
            ]
        )
        route = out.get("route", "kb")
        reason = out.get("reason", "")
    except Exception as exc:  # LLM 失败不中断
        reason = f"路由调用失败，默认检索：{exc}"
    return {
        "route": route,
        "trace": [_ev("route", "意图路由", f"判定={route}；{reason}", t0, "done" if route else "warning")],
    }


# ---------------------------------------------------------------- 闲聊直答
def direct_chat_node(state: dict) -> dict:
    t0 = time.perf_counter()
    history = (state.get("history") or [])[-6:]
    messages = [{"role": "system", "content": DIRECT_CHAT_SYSTEM}] + history + [
        {"role": "user", "content": state["question"]}
    ]
    answer = _stream_llm(messages, _get_writer())
    return {
        "answer": answer,
        "sources": [],
        "confidence": "high",
        "trace": [_ev("direct_chat", "直接回应", "无需检索，模型直接回应", t0)],
    }


# ---------------------------------------------------------------- 检索
def retrieve_node(state: dict) -> dict:
    t0 = time.perf_counter()
    query = state.get("rewritten_query") or state["question"]
    docs = store.query(query, settings.retrieve_top_k)
    if docs:
        top = ", ".join(f"{d['source']}({d['similarity']})" for d in docs[:3])
        detail = f"查询「{query}」命中 {len(docs)} 条，最高相似度：{top}"
    else:
        detail = f"查询「{query}」无命中（知识库为空或均不相似）"
    return {
        "documents": docs,
        "trace": [_ev("retrieve", "向量检索", detail, t0, "done" if docs else "warning")],
    }


# ---------------------------------------------------------------- 文档打分
def grade_node(state: dict) -> dict:
    t0 = time.perf_counter()
    docs = state.get("documents") or []
    if not docs:
        return {"graded": [], "trace": [_ev("grade", "相关性打分", "无可打分文档", t0, "warning")]}

    listing = "\n\n".join(
        f"[{i}] 来源: {d['source']} / {d.get('section', '')}（状态: {d.get('status', '现行')}）\n{_truncate(d['text'])}"
        for i, d in enumerate(docs, 1)
    )
    try:
        out = chat_json(
            [
                {"role": "system", "content": GRADE_SYSTEM},
                {"role": "user", "content": f"用户问题：{state['question']}\n\n候选文档片段：\n{listing}"},
            ]
        )
        relevant_idx = {int(i) for i in out.get("relevant", [])}
        verdicts = out.get("verdicts", [])
    except Exception as exc:  # 打分失败退化为全保留
        return {
            "graded": docs,
            "trace": [_ev("grade", "相关性打分", f"打分调用失败，全部保留：{exc}", t0, "warning")],
        }

    graded = [d for i, d in enumerate(docs, 1) if i in relevant_idx]
    reasons = "；".join(
        f"[{v.get('index')}]{'✓' if v.get('relevant') else '✗'}{v.get('reason', '')}" for v in verdicts[:5]
    )
    detail = f"{len(docs)} 条候选 → {len(graded)} 条相关。{reasons}"
    return {
        "graded": graded,
        "trace": [_ev("grade", "相关性打分", detail, t0, "done" if graded else "warning")],
    }


# ---------------------------------------------------------------- 查询改写
def rewrite_node(state: dict) -> dict:
    t0 = time.perf_counter()
    try:
        out = chat_json(
            [
                {"role": "system", "content": REWRITE_SYSTEM},
                {"role": "user", "content": f"原始问题：{state['question']}\n上一轮查询：{state.get('rewritten_query') or state['question']}"},
            ]
        )
        rewritten = out.get("rewritten", state["question"])
        analysis = out.get("analysis", "")
    except Exception as exc:
        rewritten, analysis = state["question"], f"改写失败，沿用原查询：{exc}"
    return {
        "rewritten_query": rewritten,
        "rewrite_round": state.get("rewrite_round", 0) + 1,
        "trace": [_ev("rewrite", "查询改写", f"第 {state.get('rewrite_round', 0) + 1} 轮改写：「{rewritten}」；{analysis}", t0)],
    }


# ---------------------------------------------------------------- 联网兜底
def web_search_node(state: dict) -> dict:
    t0 = time.perf_counter()
    query = state.get("rewritten_query") or state["question"]
    results: list[dict] = []
    try:
        from ddgs import DDGS

        raw = DDGS().text(query, region="cn-zh", max_results=settings.web_search_results)
        results = [
            {"title": r.get("title", ""), "url": r.get("href", ""), "snippet": _truncate(r.get("body", ""), 300)}
            for r in raw
        ]
    except Exception as exc:
        detail = f"联网搜索不可用：{exc}"
        return {"web_results": [], "used_web": True, "trace": [_ev("web_search", "联网兜底", detail, t0, "warning")]}
    detail = (
        f"查询「{query}」获得 {len(results)} 条网页结果："
        + "；".join(r["title"][:30] for r in results[:3])
        if results
        else "联网搜索无结果"
    )
    return {
        "web_results": results,
        "used_web": True,
        "trace": [_ev("web_search", "联网兜底", detail, t0, "done" if results else "warning")],
    }


# ---------------------------------------------------------------- 生成
def generate_node(state: dict) -> dict:
    t0 = time.perf_counter()
    graded, web = state.get("graded") or [], state.get("web_results") or []

    if graded:
        context = format_context(graded)
    elif web:
        context = "\n\n".join(
            f"[{i}] 来源: {r['title']}（{r['url']}）\n{r['snippet']}" for i, r in enumerate(web, 1)
        )
    else:
        context = "（无可用参考资料）"

    system = GENERATE_SYSTEM.replace("{context}", context)
    if state.get("regen_round", 0) > 0:
        reason = (state.get("reflection") or {}).get("reason", "质量自检未通过")
        system += REGENERATE_SUFFIX.replace("{reason}", reason)

    user = f"用户问题：{state['question']}"
    if state.get("rewritten_query"):
        user += f"\n（优化后检索词：{state['rewritten_query']}）"

    generation = _stream_llm(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        _get_writer(),
    )
    src_label = f"依据 {'知识库 %d 条' % len(graded) if graded else '联网结果 %d 条' % len(web) if web else '无资料'}"
    return {
        "generation": generation,
        "sources": [
            {"source": d["source"], "section": d.get("section", ""), "similarity": d.get("similarity")}
            for d in graded
        ]
        or [{"source": r["title"], "section": r["url"]} for r in web],
        "trace": [_ev("generate", "生成回答", src_label, t0)],
    }


# ---------------------------------------------------------------- 自检
def check_node(state: dict) -> dict:
    t0 = time.perf_counter()
    graded, web = state.get("graded") or [], state.get("web_results") or []
    if graded:
        context = format_context(graded)
    elif web:
        context = "\n\n".join(f"[{i}] {r['title']}：{r['snippet']}" for i, r in enumerate(web, 1))
    else:
        context = "（无可用参考资料）"

    reflection: dict = {"verdict": "pass", "grounded": True, "addresses": True, "reason": ""}
    answer, confidence = state.get("generation", ""), "high"
    try:
        out = chat_json(
            [
                {"role": "system", "content": CHECK_SYSTEM},
                {"role": "user", "content": f"用户问题：{state['question']}\n\n参考资料：\n{context}\n\n回答：\n{state.get('generation', '')}"},
            ]
        )
        grounded = bool(out.get("grounded"))
        addresses = bool(out.get("addresses"))
        reason = out.get("reason", "")
        if grounded and addresses:
            reflection = {"verdict": "pass", "grounded": True, "addresses": True, "reason": reason}
            confidence = "medium" if state.get("used_web") else "high"
            answer = state.get("generation", "")
        elif state.get("regen_round", 0) < settings.max_regen:
            reflection = {"verdict": "retry", "grounded": grounded, "addresses": addresses, "reason": reason}
            return {
                "reflection": reflection,
                "regen_round": state.get("regen_round", 0) + 1,
                "trace": [_ev("check", "质量自检", f"未通过（{'无事实依据' if not grounded else '答非所问'}）：{reason}，触发重新生成", t0, "warning")],
            }
        else:
            reflection = {"verdict": "low_accept", "grounded": grounded, "addresses": addresses, "reason": reason}
            confidence = "low"
            answer = state.get("generation", "")
    except Exception as exc:  # 自检失败：放行回答，标记未核验
        reflection = {"verdict": "pass", "grounded": None, "addresses": None, "reason": f"自检调用失败：{exc}"}
        confidence = "medium"
        answer = state.get("generation", "")

    label = {"high": "自检通过", "medium": "自检通过（含联网/未核验内容）", "low": "多轮重试后仍存疑，已附低置信提示"}[confidence]
    return {
        "reflection": reflection,
        "answer": answer,
        "confidence": confidence,
        "trace": [_ev("check", "质量自检", f"{label}：{reflection.get('reason', '')}", t0)],
    }


# ---------------------------------------------------------------- 完成
def answer_node(state: dict) -> dict:
    t0 = time.perf_counter()
    n_src = len(state.get("sources") or [])
    return {
        "answer": state.get("answer", ""),
        "sources": state.get("sources") or [],
        "confidence": state.get("confidence", "medium"),
        "trace": [_ev("answer", "完成", f"回答完成，引用来源 {n_src} 条，置信度 {state.get('confidence', 'medium')}", t0)],
    }
