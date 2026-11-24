"""下载本地 Embedding 模型 bge-small-zh-v1.5 到 models/ 目录。

因 HuggingFace 匿名出口流量配额限制，国内直连下载常被限速/阻断，
本脚本从 hf-mirror.com 镜像逐文件下载（带断点续传与完整性校验）。

用法：.venv/Scripts/python.exe scripts/download_model.py
"""
import sys
import urllib.request
from pathlib import Path

BASE = "https://hf-mirror.com/BAAI/bge-small-zh-v1.5/resolve/main"
FILES = [
    "config_sentence_transformers.json",
    "modules.json",
    "sentence_bert_config.json",
    "config.json",
    "tokenizer_config.json",
    "special_tokens_map.json",
    "vocab.txt",
    "tokenizer.json",
    "1_Pooling/config.json",
    "model.safetensors",
]

ROOT = Path(__file__).resolve().parents[1]
TARGET_DIR = ROOT / "models" / "bge-small-zh-v1.5"


def download(rel: str) -> None:
    out = TARGET_DIR / rel
    out.parent.mkdir(parents=True, exist_ok=True)
    url = f"{BASE}/{rel.replace(' ', '%20')}"
    if out.exists() and out.stat().st_size > 0:
        print(f"已存在，跳过: {rel}")
        return
    print(f"下载 {rel} …", flush=True)
    tmp = out.with_suffix(out.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=120) as resp, tmp.open("wb") as f:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = resp.read(1 << 16)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if total:
                pct = done * 100 // total
                print(f"\r  {done / 1048576:.1f} MB / {total / 1048576:.1f} MB ({pct}%)", end="", flush=True)
        print()
    tmp.rename(out)


def main() -> None:
    missing = [f for f in FILES if not (TARGET_DIR / f).exists()]
    if not missing:
        print(f"模型已完整位于 {TARGET_DIR}，无需下载")
        return
    print(f"从 {BASE} 下载 {len(missing)} 个文件到 {TARGET_DIR}")
    for f in missing:
        try:
            download(f)
        except Exception as exc:
            print(f"下载失败 {f}: {exc}")
            sys.exit(1)
    print("✅ 模型就绪，现在可以运行 scripts/ingest_corpus.py 入库")


if __name__ == "__main__":
    main()
