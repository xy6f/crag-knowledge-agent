"""聊天接口：POST /api/chat，SSE 流式推送 Agent 每一步事件与最终回答。

事件格式（text/event-stream）：
    data: {"type": "start"}
    data: {"type": "step", "step": "retrieve", "label": "向量检索", "detail": "...", "duration_ms": 120}
    data: {"type": "answer", "answer": "...", "sources": [...], "confidence": "high", "trace": [...]}
    data: {"type": "error", "message": "..."}
"""
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.agent.graph import graph
from app.config import settings
from app.llm import MissingAPIKeyError

router = APIRouter()


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    history: list[dict] = Field(default_factory=list)


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def _event_stream(req: ChatRequest) -> AsyncIterator[str]:
    yield _sse({"type": "start"})
    if not settings.api_key_configured:
        yield _sse(
            {
                "type": "error",
                "message": "尚未配置 DEEPSEEK_API_KEY。请编辑项目根目录的 .env 文件，"
                "在 DEEPSEEK_API_KEY= 后填入你的 DeepSeek API Key，然后重启服务。",
            }
        )
        return

    initial: dict = {
        "question": req.question,
        "history": req.history,
        "rewrite_round": 0,
        "regen_round": 0,
        "used_web": False,
        "trace": [],
    }
    trace: list[dict] = []
    final_patch: dict | None = None
    try:
        async for update in graph.astream(initial, config={"recursion_limit": 30}):
            for node, patch in update.items():
                if not isinstance(patch, dict):
                    continue
                for ev in patch.get("trace") or []:
                    trace.append(ev)
                    yield _sse({"type": "step", **ev})
                if node == "answer":
                    final_patch = patch
        if final_patch:
            yield _sse(
                {
                    "type": "answer",
                    "answer": final_patch.get("answer", ""),
                    "sources": final_patch.get("sources") or [],
                    "confidence": final_patch.get("confidence", "medium"),
                    "trace": trace,
                }
            )
        else:
            yield _sse({"type": "error", "message": "Agent 未能生成回答，请稍后重试。"})
    except MissingAPIKeyError as exc:
        yield _sse({"type": "error", "message": str(exc)})
    except Exception as exc:  # noqa: BLE001 — 统一转成 SSE 错误事件
        yield _sse({"type": "error", "message": f"处理失败：{exc}"})


@router.post("/api/chat")
async def chat(req: ChatRequest) -> StreamingResponse:
    return StreamingResponse(
        _event_stream(req),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
