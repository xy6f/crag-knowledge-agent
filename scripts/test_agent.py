"""命令行快速验证 Agent 图：打印每步 trace 与最终回答。

用法：.venv/Scripts/python.exe scripts/test_agent.py "你的问题"
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agent.graph import graph  # noqa: E402
from app.config import settings  # noqa: E402
from app.llm import MissingAPIKeyError  # noqa: E402


def main() -> None:
    if len(sys.argv) < 2:
        print('用法: python scripts/test_agent.py "你的问题"')
        sys.exit(1)
    if not settings.api_key_configured:
        print("❌ 尚未配置 DEEPSEEK_API_KEY，请先编辑 .env。")
        sys.exit(1)

    question = " ".join(sys.argv[1:])
    initial = {
        "question": question,
        "history": [],
        "rewrite_round": 0,
        "regen_round": 0,
        "used_web": False,
        "trace": [],
    }

    print(f"\n问题：{question}\n" + "=" * 60)
    final: dict = {}
    try:
        for update in graph.stream(initial, config={"recursion_limit": 30}):
            for node, patch in update.items():
                if not isinstance(patch, dict):
                    continue
                if node == "answer":
                    final = patch
                for ev in patch.get("trace") or []:
                    icon = "⚠️" if ev["status"] == "warning" else "🔹"
                    print(f"{icon} [{ev['step']:<10}] {ev['label']} ({ev['duration_ms']}ms)")
                    print(f"   {ev['detail']}")
        print("=" * 60)
    except MissingAPIKeyError as exc:
        print(f"❌ {exc}")
        sys.exit(1)

    print("回答：\n")
    print(final.get("answer", "(无回答)"))
    print(f"\n置信度：{final.get('confidence', '-')}")
    for s in final.get("sources") or []:
        print(f"  来源: {s.get('source')} / {s.get('section', '')}")


if __name__ == "__main__":
    main()
