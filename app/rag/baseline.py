"""朴素 RAG 基线：直接「检索 → 拼 Prompt → 生成」，无任何自反思环节。

用于与 CRAG Agent 对比评测，展示 Agentic 循环的价值。
"""
from app.config import settings
from app.llm import chat
from app.rag import store

NAIVE_SYSTEM = (
    "你是星野科技的企业知识库助手。请仅依据下面的参考资料回答用户问题；"
    "资料中没有的信息就明确说「知识库中没有相关信息」，不要编造。"
    "回答需简洁、分点，并在引用处标注来源编号如 [1]。"
)


def format_context(docs: list[dict]) -> str:
    parts = []
    for i, d in enumerate(docs, 1):
        parts.append(
            f"[{i}] 来源: {d['source']} / {d.get('section', '')}（状态: {d.get('status', '现行')}，相似度 {d.get('similarity', '-')}）\n{d['text']}"
        )
    return "\n\n".join(parts)


def naive_rag(question: str) -> dict:
    """朴素 RAG：检索 top-k 后直接生成。返回 answer / sources / docs。"""
    docs = store.query(question, settings.retrieve_top_k)
    if docs:
        context = format_context(docs)
        user_msg = f"参考资料：\n{context}\n\n用户问题：{question}"
        answer = chat(
            [
                {"role": "system", "content": NAIVE_SYSTEM},
                {"role": "user", "content": user_msg},
            ]
        )
    else:
        answer = "知识库中还没有任何文档，无法回答该问题。"
    return {
        "answer": answer,
        "docs": docs,
        "sources": [{"source": d["source"], "section": d["section"]} for d in docs],
    }
