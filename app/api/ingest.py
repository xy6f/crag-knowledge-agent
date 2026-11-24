"""知识库管理接口：文档列表 / 上传入库 / 重建知识库。"""
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.config import settings
from app.rag import loader, store

router = APIRouter()
MAX_UPLOAD_MB = 20


@router.get("/api/documents")
async def list_documents() -> dict:
    return {"sources": store.list_sources(), "total_chunks": store.count()}


@router.post("/api/ingest")
async def ingest(file: UploadFile = File(...)) -> dict:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in loader.SUPPORTED_SUFFIX:
        raise HTTPException(400, f"不支持的文件类型 {suffix}，支持 md/txt/pdf")

    settings_uploads = Path(settings.uploads_dir)
    settings_uploads.mkdir(parents=True, exist_ok=True)
    save_path = settings_uploads / f"{uuid.uuid4().hex[:8]}_{Path(file.filename).name}"
    with save_path.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    try:
        chunks = loader.load_path(save_path, settings.chunk_size, settings.chunk_overlap)
        added = store.add_chunks(chunks)
    except Exception as exc:
        save_path.unlink(missing_ok=True)
        raise HTTPException(500, f"入库失败：{exc}") from exc
    return {"filename": file.filename, "chunks": added, "total_chunks": store.count()}


@router.post("/api/rebuild")
async def rebuild() -> dict:
    """清空向量库并重新入库 data/corpus 下的全部示例语料。"""
    corpus = Path(settings.corpus_dir)
    if not corpus.exists():
        raise HTTPException(404, "语料目录不存在")
    store.reset()
    chunks = loader.load_dir(corpus, settings.chunk_size, settings.chunk_overlap)
    added = store.add_chunks(chunks)
    return {"chunks": added, "total_chunks": store.count()}
