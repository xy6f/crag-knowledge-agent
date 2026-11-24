"""Chroma 向量库封装：本地持久化，cosine 相似度。"""
import hashlib
import threading

import chromadb
from chromadb.config import Settings as ChromaSettings

from app.config import settings
from app.rag.embeddings import embed, embed_one

_client = None
_col = None
_lock = threading.Lock()


def collection():
    global _client, _col
    if _col is None:
        with _lock:
            if _col is None:
                _client = chromadb.PersistentClient(
                    path=settings.chroma_dir,
                    settings=ChromaSettings(anonymized_telemetry=False),
                )
                _col = _client.get_or_create_collection(
                    name="knowledge_base",
                    metadata={"hnsw:space": "cosine"},
                )
    return _col


def _chunk_id(chunk: dict) -> str:
    raw = f"{chunk['source']}::{chunk['section']}::{chunk['text']}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def add_chunks(chunks: list[dict]) -> int:
    """入库（幂等：同内容 chunk 用相同 id 覆盖）。返回新增条数。"""
    if not chunks:
        return 0
    col = collection()
    ids = [_chunk_id(c) for c in chunks]
    vectors = embed([c["text"] for c in chunks])
    col.upsert(
        ids=ids,
        embeddings=vectors,
        documents=[c["text"] for c in chunks],
        metadatas=[
            {
                "source": c["source"],
                "title": c["title"],
                "section": c["section"],
                "status": c["status"],
            }
            for c in chunks
        ],
    )
    return len(chunks)


def query(text: str, k: int | None = None) -> list[dict]:
    """向量检索，返回按相似度降序的 chunk（similarity ∈ [0,1]，越大越相关）。"""
    k = k or settings.retrieve_top_k
    col = collection()
    if col.count() == 0:
        return []
    res = col.query(query_embeddings=[embed_one(text)], n_results=min(k, col.count()))
    docs = []
    for i in range(len(res["ids"][0])):
        meta = res["metadatas"][0][i]
        distance = res["distances"][0][i]
        docs.append(
            {
                "text": res["documents"][0][i],
                "source": meta.get("source", ""),
                "title": meta.get("title", ""),
                "section": meta.get("section", ""),
                "status": meta.get("status", "现行"),
                "similarity": round(1.0 - distance, 4),
            }
        )
    return docs


def list_sources() -> list[dict]:
    """按来源文件聚合统计。"""
    col = collection()
    data = col.get(include=["metadatas"])
    stats: dict[str, dict] = {}
    for meta in data["metadatas"]:
        src = meta.get("source", "")
        entry = stats.setdefault(
            src, {"source": src, "title": meta.get("title", ""), "status": meta.get("status", "现行"), "chunks": 0}
        )
        entry["chunks"] += 1
    return sorted(stats.values(), key=lambda x: x["source"])


def count() -> int:
    return collection().count()


def delete_source(source: str) -> None:
    collection().delete(where={"source": source})


def reset() -> None:
    """清空知识库（重新入库前用）。"""
    col = collection()
    data = col.get(include=[])
    if data["ids"]:
        col.delete(ids=data["ids"])
