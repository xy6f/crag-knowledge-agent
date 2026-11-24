"""把 data/corpus 下的示例语料入库（向量库默认先清空重建）。

用法：.venv/Scripts/python.exe scripts/ingest_corpus.py [--no-reset]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings  # noqa: E402
from app.rag import loader, store  # noqa: E402


def main() -> None:
    corpus = Path(settings.corpus_dir)
    files = [p for p in sorted(corpus.rglob("*")) if p.suffix.lower() in loader.SUPPORTED_SUFFIX]
    if not files:
        print(f"语料目录为空：{corpus}")
        sys.exit(1)

    if "--no-reset" not in sys.argv:
        print("清空旧索引…")
        store.reset()

    chunks = loader.load_dir(corpus, settings.chunk_size, settings.chunk_overlap)
    print(f"加载 {len(files)} 个文件 → {len(chunks)} 个 chunk，开始向量化入库…")
    added = store.add_chunks(chunks)
    print(f"入库完成：新增/更新 {added} 条，知识库总计 {store.count()} 条")
    for src in store.list_sources():
        mark = "（已废止）" if "废止" in src.get("status", "") else ""
        print(f"  - {src['source']}: {src['chunks']} 块 {mark}")


if __name__ == "__main__":
    main()
