"""全局配置：从项目根目录的 .env 读取。"""
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# 项目根目录 = app/ 的上一级
ROOT_DIR = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---- DeepSeek ----
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    llm_temperature: float = 0.2

    # ---- Embedding（本地 CPU）----
    hf_endpoint: str = "https://hf-mirror.com"
    embedding_model: str = "BAAI/bge-small-zh-v1.5"

    # ---- 路径 ----
    chroma_dir: str = str(ROOT_DIR / "data" / "chroma")
    corpus_dir: str = str(ROOT_DIR / "data" / "corpus")
    uploads_dir: str = str(ROOT_DIR / "data" / "uploads")
    frontend_dir: str = str(ROOT_DIR / "frontend")

    # ---- RAG 参数 ----
    chunk_size: int = 500
    chunk_overlap: int = 80
    retrieve_top_k: int = 5
    final_top_k: int = 3
    max_rewrite_rounds: int = 2
    max_regen: int = 1
    web_search_results: int = 4

    @property
    def api_key_configured(self) -> bool:
        return bool(self.deepseek_api_key.strip())


settings = Settings()
