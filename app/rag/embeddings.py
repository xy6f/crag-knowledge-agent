"""本地 Embedding：bge-small-zh-v1.5（CPU），首次调用时加载模型。"""
import os
import threading

from app.config import settings

_model = None
_lock = threading.Lock()


def _get_model():
    global _model
    if _model is None:
        with _lock:
            if _model is None:
                # HF 国内镜像要在 import 前生效；禁用 hf-xet（它会绕过镜像直连被墙的 CDN）
                if settings.hf_endpoint:
                    os.environ.setdefault("HF_ENDPOINT", settings.hf_endpoint)
                os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
                from sentence_transformers import SentenceTransformer

                _model = SentenceTransformer(settings.embedding_model)
    return _model


def embed(texts: list[str]) -> list[list[float]]:
    """批量向量化（归一化，配合 cosine 相似度）。"""
    if not texts:
        return []
    model = _get_model()
    vectors = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    return vectors.tolist()


def embed_one(text: str) -> list[float]:
    return embed([text])[0]
