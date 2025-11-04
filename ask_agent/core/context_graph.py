# core/context_graph.py

from dataclasses import dataclass, field
from typing import List, Dict, Optional
import asyncio
import time

# =========================
# 基础上下文图谱
# =========================
@dataclass
class ContextGraph:
    """
    上下文语义图谱：
    存储当前会话中涉及的所有指标、时间信息、节点及依赖关系。
    """
    indicators: List[str] = field(default_factory=list)
    times: List[Dict] = field(default_factory=list)
    relations: List[Dict] = field(default_factory=list)
    nodes: List[tuple] = field(default_factory=list)  # 新增 nodes, 存储 (indicator, timeString, timeType)

    def add_indicator(self, name: str):
        if name and name not in self.indicators:
            self.indicators.append(name)

    def add_time(self, time_str: str, time_type: Optional[str]):
        node = {"timeString": time_str, "timeType": time_type}
        if time_str and node not in self.times:
            self.times.append(node)

    def add_node(self, indicator: Optional[str], time_str: Optional[str], time_type: Optional[str] = None):
        """
        同时更新 indicators, times, nodes 去重
        """
        if indicator:
            self.add_indicator(indicator)
        if time_str:
            self.add_time(time_str, time_type)
        if indicator or time_str:
            node_tuple = (indicator, time_str, time_type)
            if node_tuple not in self.nodes:
                self.nodes.append(node_tuple)

    def link_last(self):
        """预留接口：建立节点依赖关系"""
        pass

    def to_state(self):
        return {
            "graph": {
                "indicators": self.indicators,
                "times": self.times,
                "relations": self.relations,
                "nodes": self.nodes
            }
        }

    @classmethod
    def from_state(cls, state: dict):
        graph_data = state.get("graph", {})
        return cls(
            indicators=graph_data.get("indicators", []),
            times=graph_data.get("times", []),
            relations=graph_data.get("relations", []),
            nodes=graph_data.get("nodes", [])
        )


# =========================
# 用户上下文管理器
# =========================
class ContextManager:
    """
    管理每个 user_id 的 query 历史和 context_graph
    """
    SESSION_EXPIRE_SECONDS = 30 * 60  # 30分钟过期

    def __init__(self):
        self._user_contexts: Dict[str, Dict] = {}
        self._lock = asyncio.Lock()

    def _now(self):
        return time.time()

    async def append_query(self, user_id: str, query: Dict):
        """
        添加一次查询：
          - query 例：{"user_input": "...", "indicator": "...", "formula": "...", "timeString": "...", "timeType": "...", "intent": "..."}
        """
        async with self._lock:
            ctx = self._user_contexts.get(user_id)
            if not ctx:
                ctx = {"history": [], "graph": ContextGraph(), "last_active": self._now()}
                self._user_contexts[user_id] = ctx

            # ✅ 只在成功查询后记录 history
            ctx["history"].append(query)
            ctx["last_active"] = self._now()

            # 更新 graph 节点
            ctx["graph"].add_node(query.get("indicator"), query.get("timeString"), query.get("timeType"))

            return ctx

    async def get_recent(self, user_id: str, n: Optional[int] = None):
        """
        获取最近 n 条查询历史
        """
        async with self._lock:
            ctx = self._user_contexts.get(user_id)
            if not ctx:
                return []
            return ctx["history"][-n:] if n else ctx["history"]

    async def get_graph(self, user_id: str) -> ContextGraph:
        """
        获取当前 graph
        """
        async with self._lock:
            ctx = self._user_contexts.get(user_id)
            return ctx["graph"] if ctx else ContextGraph()

    async def clear(self, user_id: str):
        """
        清空用户 session
        """
        async with self._lock:
            if user_id in self._user_contexts:
                del self._user_contexts[user_id]

    async def cleanup_expired(self):
        """
        清理过期 session
        """
        async with self._lock:
            now_ts = self._now()
            expired = [uid for uid, ctx in self._user_contexts.items()
                       if now_ts - ctx["last_active"] > self.SESSION_EXPIRE_SECONDS]
            for uid in expired:
                del self._user_contexts[uid]
            return expired
