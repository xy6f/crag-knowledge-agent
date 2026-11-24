"""LangGraph 状态定义。

trace 使用 Annotated[list, operator.add] 归并器：每个节点只返回「新增」的
trace 事件，框架自动累加，SSE 流式推送时也只取增量事件。
"""
import operator
from typing import Annotated, TypedDict


class AgentState(TypedDict, total=False):
    # 输入
    question: str
    history: list[dict]  # [{"role": "user"|"assistant", "content": str}]

    # 路由
    route: str  # "chat"（闲聊直答）| "kb"（走知识库）

    # 检索与打分
    documents: list[dict]  # 向量检索原始结果
    graded: list[dict]  # 相关性打分后保留的文档
    rewritten_query: str  # 改写后的查询（未改写时为空）
    rewrite_round: int  # 已改写轮数

    # 联网兜底
    web_results: list[dict]  # [{"title","url","snippet"}]
    used_web: bool

    # 生成与自检
    generation: str  # generate 节点的原始输出
    reflection: dict  # {"grounded": bool, "addresses": bool, "reason": str}
    regen_round: int  # 已重新生成次数

    # 输出
    answer: str
    sources: list[dict]  # [{"source","section","url"?}]
    confidence: str  # "high" | "medium" | "low"

    # 全程决策轨迹（归并累加）
    trace: Annotated[list[dict], operator.add]
