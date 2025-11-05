# core/context_graph.py

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple, Any
import asyncio
import time
import logging

logger = logging.getLogger("context_graph")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")

@dataclass
class ContextGraph:
    """
    上下文语义图谱（轻量实现）：
    - nodes: List[Dict] 每个 node 结构：{"id": int, "indicator": str, "timeString": str, "timeType": str}
    - relations: List[Dict] 每个 relation：{"type": str, "source": id, "target": id, "meta": dict}
    提供查找/更新/解析 compare pair 的能力。
    """
    nodes: List[Dict[str, Any]] = field(default_factory=list)
    relations: List[Dict[str, Any]] = field(default_factory=list)
    _next_id: int = field(default=1, init=False, repr=False)

    # ---------------------
    # 节点管理
    # ---------------------
    def _alloc_id(self) -> int:
        nid = self._next_id
        self._next_id += 1
        return nid

    def add_node(self, indicator: Optional[str], time_str: Optional[str], time_type: Optional[str] = None) -> int:
        """
        添加节点（如果同 indicator+timeString 存在则返回已有 id）。
        返回 node id。
        """
        if not indicator and not time_str:
            raise ValueError("indicator/timeString 至少要有一项")

        # 查重：indicator + timeString
        for n in self.nodes:
            if n.get("indicator") == indicator and n.get("timeString") == time_str:
                logger.debug("节点已存在 -> reuse id=%s: %s @ %s", n["id"], indicator, time_str)
                return n["id"]

        nid = self._alloc_id()
        node = {"id": nid, "indicator": indicator, "timeString": time_str, "timeType": time_type}
        self.nodes.append(node)
        logger.info("🆕 ContextGraph.add_node -> id=%s, indicator=%s, time=%s", nid, indicator, time_str)
        return nid

    def find_node(self, indicator: Optional[str] = None, timeString: Optional[str] = None) -> Optional[int]:
        """按 indicator + timeString 精确匹配返回 id，否则 None"""
        for n in self.nodes:
            if indicator is not None and timeString is not None:
                if n.get("indicator") == indicator and n.get("timeString") == timeString:
                    return n["id"]
            elif indicator is not None and timeString is None:
                if n.get("indicator") == indicator:
                    return n["id"]
        return None

    def get_node(self, node_id: int) -> Optional[Dict[str, Any]]:
        for n in self.nodes:
            if n["id"] == node_id:
                return n
        return None

    def update_node(self, old_indicator: str, new_indicator: str):
        """
        替换节点中的指标名（用于 pipeline 在最终确定指标后替换）
        """
        updated = False
        for n in self.nodes:
            if n.get("indicator") == old_indicator:
                n["indicator"] = new_indicator
                updated = True
        if updated:
            logger.info("🔁 ContextGraph.update_node: %s -> %s", old_indicator, new_indicator)

    # ---------------------
    # 关系管理
    # ---------------------
    def add_relation(self, rel_type: str, source_id: Optional[int] = None, target_id: Optional[int] = None, meta: Optional[Dict] = None):
        """
        添加 relation：
        - rel_type: 如 "compare", "time_shift", "sequence"
        - source_id/target_id: node id（可为 None，意味着未明确指定）
        """
        rel = {"type": rel_type, "source": source_id, "target": target_id, "meta": meta or {}}
        # 去重判断（简单比较字典）
        if rel not in self.relations:
            self.relations.append(rel)
            logger.info("🔗 ContextGraph.add_relation: %s (source=%s target=%s) meta=%s", rel_type, source_id, target_id, meta or {})
        else:
            logger.debug("🟡 relation already exists: %s", rel)

    def get_relations(self, rel_type: Optional[str] = None) -> List[Dict[str, Any]]:
        if rel_type:
            return [r for r in self.relations if r.get("type") == rel_type]
        return list(self.relations)

    # ---------------------
    # 辅助解析：resolve compare
    # ---------------------
    def resolve_compare_nodes(self, user_input: Optional[str] = None) -> Optional[Tuple[int, int]]:
        """
        解析需要对比的两个节点 id。
        策略（优先级）：
          1. 如果已有 relations 中存在 type == 'compare' 且 source/target 都不为空，返回最新一对
          2. 否则如果 nodes >= 2，返回最后两个节点 id
          3. 否则返回 None
        该函数不触发网络/LLM 查询，仅基于 graph 内容进行解析。
        """
        # 1) find explicit compare relation with source&target
        for r in reversed(self.relations):
            if r.get("type") == "compare" and r.get("source") and r.get("target"):
                logger.debug("resolve_compare_nodes: found explicit relation %s", r)
                return r.get("source"), r.get("target")

        # 2) fallback to last two nodes
        if len(self.nodes) >= 2:
            a = self.nodes[-2]["id"]
            b = self.nodes[-1]["id"]
            logger.debug("resolve_compare_nodes: fallback to last two nodes -> %s, %s", a, b)
            return a, b

        logger.debug("resolve_compare_nodes: cannot resolve compare pair")
        return None

    # ---------------------
    # 序列化/反序列化
    # ---------------------
    def to_state(self) -> Dict[str, Any]:
        return {"graph": {"nodes": self.nodes, "relations": self.relations, "_next_id": self._next_id}}

    @classmethod
    def from_state(cls, state: Dict[str, Any]):
        g = cls()
        graph_data = state.get("graph", {}) if isinstance(state, dict) else {}
        nodes = graph_data.get("nodes", []) or []
        relations = graph_data.get("relations", []) or []
        g.nodes = nodes.copy()
        g.relations = relations.copy()
        g._next_id = graph_data.get("_next_id", max([n["id"] for n in g.nodes], default=0) + 1)
        return g
        
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
