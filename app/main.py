"""FastAPI 入口：挂载 API 路由与前端静态页面。"""
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api import chat, ingest
from app.config import settings

app = FastAPI(title="Agentic RAG 知识库问答", version="1.0.0")

app.include_router(chat.router)
app.include_router(ingest.router)


@app.get("/api/health")
async def health() -> dict:
    from app.rag import store

    return {
        "status": "ok",
        "api_key_configured": settings.api_key_configured,
        "embedding_model": settings.embedding_model,
        "total_chunks": store.count(),
    }


# 前端静态页面（挂最后，避免吞掉 /api 路由）
app.mount("/", StaticFiles(directory=settings.frontend_dir, html=True), name="frontend")
