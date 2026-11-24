"""LangGraph 状态机组装（CRAG + Self-RAG 混合流程）：

    START → route ─┬─(chat)→ direct_chat → answer → END
                   └─(kb)→ retrieve → grade ─┬─(有相关)→ generate → check ─┬─(通过/放行)→ answer
                                             ├─(全不相关且未超限)→ rewrite → retrieve
                                             └─(超限)→ web_search → generate
    check 不通过且未超重试上限时回到 generate 重新生成。
"""
from langgraph.graph import END, START, StateGraph

from app.agent import nodes
from app.agent.state import AgentState


def after_route(state: dict) -> str:
    return "direct_chat" if state.get("route") == "chat" else "retrieve"


def after_grade(state: dict) -> str:
    if state.get("graded"):
        return "generate"
    if state.get("rewrite_round", 0) < _max_rewrite_rounds():
        return "rewrite"
    return "web_search"


def after_check(state: dict) -> str:
    verdict = (state.get("reflection") or {}).get("verdict")
    return "generate" if verdict == "retry" else "answer"


def _max_rewrite_rounds() -> int:
    from app.config import settings

    return settings.max_rewrite_rounds


def build_graph():
    g = StateGraph(AgentState)
    g.add_node("route", nodes.route_node)
    g.add_node("direct_chat", nodes.direct_chat_node)
    g.add_node("retrieve", nodes.retrieve_node)
    g.add_node("grade", nodes.grade_node)
    g.add_node("rewrite", nodes.rewrite_node)
    g.add_node("web_search", nodes.web_search_node)
    g.add_node("generate", nodes.generate_node)
    g.add_node("check", nodes.check_node)
    g.add_node("answer", nodes.answer_node)

    g.add_edge(START, "route")
    g.add_conditional_edges("route", after_route, {"direct_chat": "direct_chat", "retrieve": "retrieve"})
    g.add_edge("direct_chat", "answer")
    g.add_edge("retrieve", "grade")
    g.add_conditional_edges("grade", after_grade, {"generate": "generate", "rewrite": "rewrite", "web_search": "web_search"})
    g.add_edge("rewrite", "retrieve")
    g.add_edge("web_search", "generate")
    g.add_edge("generate", "check")
    g.add_conditional_edges("check", after_check, {"generate": "generate", "answer": "answer"})
    g.add_edge("answer", END)
    return g.compile()


graph = build_graph()
