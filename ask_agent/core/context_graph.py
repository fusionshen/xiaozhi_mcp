# core/context_graph.py
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
import asyncio
import time

# =========================
# 基础上下文图谱
# =========================
@dataclass
class ContextGraph:
    """
    上下文语义图谱：
    存储会话中涉及的所有标准指标、时间信息、节点及语义关系。
    """
    indicators: List[str] = field(default_factory=list)
    times: List[Dict] = field(default_factory=list)
    relations: List[Dict] = field(default_factory=list)
    nodes: List[Tuple[str, str, str]] = field(default_factory=list)

    # ---------------------
    # 指标 / 时间添加
    # ---------------------
    def add_indicator(self, name: str):
        """添加唯一指标"""
        if name and name not in self.indicators:
            self.indicators.append(name)

    def add_time(self, time_str: str, time_type: Optional[str]):
        """添加唯一时间"""
        node = {"timeString": time_str, "timeType": time_type}
        if time_str and node not in self.times:
            self.times.append(node)

    # ---------------------
    # 节点添加
    # ---------------------
    def add_node(self, indicator: Optional[str], time_str: Optional[str], time_type: Optional[str] = None):
        """
        新增标准指标节点：
        - 自动去重
        - 保证节点为 pipeline 最终确认指标
        """
        if indicator:
            self.add_indicator(indicator)
        if time_str:
            self.add_time(time_str, time_type)

        if indicator or time_str:
            node_tuple = (indicator, time_str, time_type)
            if node_tuple not in self.nodes:
                self.nodes.append(node_tuple)

    # ---------------------
    # 更新节点（如 pipeline 确认后替换指标）
    # ---------------------
    def update_node(self, old_indicator: str, new_indicator: str):
        """
        当 pipeline 最终确定指标后，用新指标替换旧指标节点。
        """
        updated_nodes = []
        for node in self.nodes:
            indicator, t_str, t_type = node
            if indicator == old_indicator:
                updated_nodes.append((new_indicator, t_str, t_type))
            else:
                updated_nodes.append(node)
        self.nodes = updated_nodes

        # 更新 indicators 列表
        if old_indicator in self.indicators:
            self.indicators.remove(old_indicator)
        if new_indicator not in self.indicators:
            self.indicators.append(new_indicator)

    # ---------------------
    # 语义关系添加
    # ---------------------
    def add_relation(self, rel_type: str, node1: Tuple[str, str, str], node2: Tuple[str, str, str]):
        """
        建立语义关系（如 compare、time_shift、expand）
        :param rel_type: 关系类型（compare / time_shift / expand / sequence）
        :param node1: 起点节点 (indicator, timeString, timeType)
        :param node2: 终点节点 (indicator, timeString, timeType)
        """
        if not node1 or not node2:
            return

        relation = {"type": rel_type, "from": node1, "to": node2}
        if relation not in self.relations:
            self.relations.append(relation)

    def link_last(self, rel_type: str = "sequence"):
        """建立最近两个节点的关系（如时间序列关系）"""
        if len(self.nodes) >= 2:
            self.add_relation(rel_type, self.nodes[-2], self.nodes[-1])

    # ---------------------
    # 序列化接口
    # ---------------------
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
          - 仅在公式与时间均确定后记录
          - 自动建立时间或比较关系
        """
        async with self._lock:
            ctx = self._user_contexts.get(user_id)
            if not ctx:
                ctx = {"history": [], "graph": ContextGraph(), "last_active": self._now()}
                self._user_contexts[user_id] = ctx

            graph: ContextGraph = ctx["graph"]

            # ✅ 添加节点
            graph.add_node(query.get("indicator"), query.get("timeString"), query.get("timeType"))

            # ✅ 自动关系建立
            intent = query.get("intent")
            if intent == "compare" and len(graph.nodes) >= 2:
                graph.add_relation("compare", graph.nodes[-2], graph.nodes[-1])
            elif intent == "same_indicator_new_time":
                graph.link_last("time_shift")

            ctx["history"].append(query)
            ctx["last_active"] = self._now()
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


# ============ 示例 ============
if __name__ == "__main__":
    g = ContextGraph()

    # 添加两个节点
    g.add_node("高炉工序能耗", "2025-11-04", "DAY")
    g.add_node("高炉工序能耗实绩报出值", "2025-11-03", "DAY")

    # 建立 compare 语义关系
    g.add_relation(
        "compare",
        ("高炉工序能耗", "2025-11-04", "DAY"),
        ("高炉工序能耗实绩报出值", "2025-11-03", "DAY")
    )

    # 模拟 pipeline 确认指标
    g.update_node("高炉工序能耗", "高炉工序能耗实绩报出值")

    print("🧠 ContextGraph:", g.to_state())
