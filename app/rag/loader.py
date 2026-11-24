"""文档加载与分块：md/txt/pdf → 带元数据的 chunk 列表。

chunk 结构：
    {"text": str, "source": str, "title": str, "section": str, "status": str}
status 用于陷阱文档场景：如「已废止」的旧版制度会在检索打分阶段被降权/排除。
"""
import re
from pathlib import Path

SUPPORTED_SUFFIX = {".md", ".txt", ".pdf"}


def _detect_status(text: str) -> str:
    """从文档开头识别状态标记，如 `> 状态：已废止（自2025-01-01起停止执行）`。"""
    head = text[:400]
    m = re.search(r"状态[：:]\s*([^\n]+)", head)
    return m.group(1).strip() if m else "现行"


def _split_sections(text: str) -> list[tuple[str, str]]:
    """md 按标题切段，返回 [(段标题, 段正文)]；无标题文本整段返回。"""
    parts = re.split(r"\n(?=#{1,4}\s)", text)
    sections = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        m = re.match(r"#{1,4}\s+(.+)", part)
        title = m.group(1).strip() if m else ""
        sections.append((title, part))
    return sections


def _split_long(text: str, max_len: int, overlap: int) -> list[str]:
    """对超长段落按句子边界二次切分，带重叠。"""
    if len(text) <= max_len:
        return [text]
    # 按句子切（中英文句号/问叹号/换行）
    sentences = re.split(r"(?<=[。！？!?;\n])", text)
    chunks, buf = [], ""
    for s in sentences:
        if len(buf) + len(s) > max_len and buf:
            chunks.append(buf.strip())
            buf = buf[-overlap:] if overlap < len(buf) else buf
        buf += s
    if buf.strip():
        chunks.append(buf.strip())
    return [c for c in chunks if c.strip()]


def chunk_text(
    text: str,
    source: str,
    title: str,
    chunk_size: int,
    chunk_overlap: int,
) -> list[dict]:
    """把一份文档文本切成 chunk 列表。"""
    status = _detect_status(text)
    chunks: list[dict] = []
    for sec_title, sec_body in _split_sections(text):
        if len(sec_body) < 30:  # 跳过过短碎段
            continue
        for piece in _split_long(sec_body, chunk_size, chunk_overlap):
            chunks.append(
                {
                    "text": piece,
                    "source": source,
                    "title": title,
                    "section": sec_title or title,
                    "status": status,
                }
            )
    return chunks


def _extract_pdf(path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def load_path(path: Path, chunk_size: int, chunk_overlap: int) -> list[dict]:
    """加载单个文件（md/txt/pdf）并分块。"""
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_SUFFIX:
        raise ValueError(f"不支持的文件类型: {suffix}（支持 {', '.join(sorted(SUPPORTED_SUFFIX))}）")

    if suffix == ".pdf":
        text = _extract_pdf(path)
        title = path.stem
    else:
        text = path.read_text(encoding="utf-8", errors="ignore")
        m = re.match(r"#\s+(.+)", text)
        title = m.group(1).strip() if m else path.stem

    if not text.strip():
        return []
    return chunk_text(text, source=path.name, title=title, chunk_size=chunk_size, chunk_overlap=chunk_overlap)


def load_dir(
    dir_path: Path,
    chunk_size: int,
    chunk_overlap: int,
) -> list[dict]:
    """加载目录下所有支持格式的文档并分块。"""
    all_chunks: list[dict] = []
    for path in sorted(dir_path.rglob("*")):
        if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIX:
            all_chunks.extend(load_path(path, chunk_size, chunk_overlap))
    return all_chunks
