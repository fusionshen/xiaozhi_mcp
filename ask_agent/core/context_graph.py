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
        """
        query 字段包含:
        {
            "user_input": str,
            "indicator": Optional[str],
            "timeString": Optional[str],
            "timeType": Optional[str],
            "intent": Optional[str],
            "formula_candidates": Optional[list]
        }
        """
        async with self._lock:
            ctx = self._user_contexts.get(user_id)
            if not ctx:
                ctx = {"history": [], "graph": ContextGraph(), "last_active": self._now()}
                self._user_contexts[user_id] = ctx

            ctx["history"].append(query)
            ctx["last_active"] = self._now()

            # 更新 graph
            if query.get("indicator"):
                ctx["graph"].add_indicator(query["indicator"])
            if query.get("timeString"):
                ctx["graph"].add_time(query["timeString"], query.get("timeType"))

            return ctx

    async def get_recent(self, user_id: str, n: Optional[int] = None):
        async with self._lock:
            ctx = self._user_contexts.get(user_id)
            if not ctx:
                return []
            if n:
                return ctx["history"][-n:]
            return ctx["history"]

    async def get_graph(self, user_id: str) -> ContextGraph:
        async with self._lock:
            ctx = self._user_contexts.get(user_id)
            if not ctx:
                return ContextGraph()
            return ctx["graph"]

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

# =========================
# 测试框架
# =========================
if __name__ == "__main__":
    import asyncio

    async def test():
        cm = ContextManager()
        user_id = "test_user"

        queries = [
            {"user_input": "今天是什么日期？", "indicator": None, "timeString": "2025-10-28", "timeType": "DAY", "intent": "ask_time"},
            {"user_input": "高炉工序能耗是多少", "indicator": "高炉工序能耗", "timeString": "2025-10-28", "timeType": "DAY", "intent": "new_query"},
            {"user_input": "那昨天的呢？", "indicator": "高炉工序能耗", "timeString": "2025-10-27", "timeType": "DAY", "intent": "same_indicator_new_time"},
            {"user_input": "1#和3#分别是多少", "indicator": "高炉工序能耗", "timeString": None, "timeType": None, "intent": "expand"},
            {"user_input": "平均是多少", "indicator": None, "timeString": None, "timeType": None, "intent": "aggregate"}
        ]

        for q in queries:
            ctx = await cm.append_query(user_id, q)
            recent = await cm.get_recent(user_id)
            graph = await cm.get_graph(user_id)
            print(f"\n用户输入: {q['user_input']}")
            print(f"最近历史: {recent}")
            print(f"Graph indicators: {graph.indicators}")
            print(f"Graph times: {graph.times}")

        # 清理测试
        expired = await cm.cleanup_expired()
        print(f"清理过期会话: {expired}")

    asyncio.run(test())
