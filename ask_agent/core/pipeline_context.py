# core/pipeline_context.py
"""
统一管理各用户的 ContextGraph 对象。
便于 pipeline 与 pipeline_handlers 共享状态。
"""

from core.context_graph import ContextGraph

# 内存缓存：用户 ID -> ContextGraph
_graph_store: dict[str, ContextGraph] = {}


def get_graph(user_id: str) -> ContextGraph | None:
    """获取用户的 ContextGraph"""
    return _graph_store.get(user_id)


def set_graph(user_id: str, graph: ContextGraph) -> None:
    """设置或更新用户的 ContextGraph"""
    _graph_store[user_id] = graph


def remove_graph(user_id: str) -> None:
    """删除用户对应的 ContextGraph"""
    _graph_store.pop(user_id, None)


def all_graphs() -> dict[str, ContextGraph]:
    """获取所有用户的图谱"""
    return _graph_store
