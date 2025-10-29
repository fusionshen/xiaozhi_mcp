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
    存储当前会话中涉及的所有指标、时间信息和依赖关系。
    """
    indicators: List[str] = field(default_factory=list)
    times: List[Dict] = field(default_factory=list)
    relations: List[Dict] = field(default_factory=list)

    def add_indicator(self, name: str):
        if name and name not in self.indicators:
            self.indicators.append(name)

    def add_time(self, time_str: str, time_type: Optional[str]):
        node = {"timeString": time_str, "timeType": time_type}
        if time_str and node not in self.times:
            self.times.append(node)

    def add_node(self, indicator: Optional[str], time: Optional[str], time_type: Optional[str] = None):
        if indicator:
            self.add_indicator(indicator)
        if time:
            self.add_time(time, time_type)

    def link_last(self):
        """预留接口：建立节点依赖关系"""
        pass

    def to_state(self):
        return {"graph": {"indicators": self.indicators, "times": self.times}}

    @classmethod
    def from_state(cls, state: dict):
        graph_data = state.get("graph", {})
        return cls(**graph_data)

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
        async with self._lock:
            ctx = self._user_contexts.get(user_id)
            if not ctx:
                ctx = {"history": [], "graph": ContextGraph(), "last_active": self._now()}
                self._user_contexts[user_id] = ctx

            ctx["history"].append(query)
            ctx["last_active"] = self._now()

            # 更新 graph
            ctx["graph"].add_node(query.get("indicator"), query.get("timeString"), query.get("timeType"))

            return ctx

    async def get_recent(self, user_id: str, n: Optional[int] = None):
        async with self._lock:
            ctx = self._user_contexts.get(user_id)
            if not ctx:
                return []
            return ctx["history"][-n:] if n else ctx["history"]

    async def get_graph(self, user_id: str) -> ContextGraph:
        async with self._lock:
            ctx = self._user_contexts.get(user_id)
            return ctx["graph"] if ctx else ContextGraph()

    async def clear(self, user_id: str):
        async with self._lock:
            if user_id in self._user_contexts:
                del self._user_contexts[user_id]

    async def cleanup_expired(self):
        async with self._lock:
            now_ts = self._now()
            expired = [uid for uid, ctx in self._user_contexts.items()
                       if now_ts - ctx["last_active"] > self.SESSION_EXPIRE_SECONDS]
            for uid in expired:
                del self._user_contexts[uid]
            return expired
