# core/context_graph.py

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple, Any
import asyncio
import time
import uuid
import re
import logging

logger = logging.getLogger("context_graph")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")

# =========================
# 基础上下文图谱
# =========================
@dataclass
class Node:
    id: str
    indicator: Optional[str]
    timeString: Optional[str]
    timeType: Optional[str]
    meta: Dict[str, Any] = field(default_factory=dict)

@dataclass
class Relation:
    id: str
    type: str
    source: str
    target: str
    meta: Dict[str, Any] = field(default_factory=dict)

@dataclass
class ContextGraph:
    """
    上下文语义图谱：
    - nodes: 列表，每个 node 有唯一 id 与 indicator/time
    - relations: 语义关系（compare / time_shift / sequence / custom）
    - indicators / times: 便捷索引（保持与 nodes 同步）
    """
    indicators: List[str] = field(default_factory=list)
    times: List[Dict] = field(default_factory=list)
    relations: List[Dict] = field(default_factory=list)
    nodes: List[Tuple[str, Optional[str], Optional[str], Optional[str]]] = field(default_factory=list)
    # nodes entries are tuples: (id, indicator, timeString, timeType)

    # ---------------------
    # 内部辅助
    # ---------------------
    def _now(self):
        return time.time()

    def _new_id(self, prefix: str = "n") -> str:
        return f"{prefix}{uuid.uuid4().hex[:8]}"

    # ---------------------
    # 指标 / 时间添加（同步索引）
    # ---------------------
    def _add_indicator_index(self, name: Optional[str]):
        if not name:
            return
        if name not in self.indicators:
            self.indicators.append(name)

    def _add_time_index(self, time_str: Optional[str], time_type: Optional[str]):
        if not time_str:
            return
        node = {"timeString": time_str, "timeType": time_type}
        if node not in self.times:
            self.times.append(node)

    # ---------------------
    # 节点操作
    # ---------------------
    def add_node(self, indicator: Optional[str], time_str: Optional[str], time_type: Optional[str] = None) -> str:
        """
        添加节点（仅接受 pipeline 最终确认的 indicator/time）：
        - 返回节点 id（若已存在则返回已存在节点 id）
        - 去重逻辑：通过 (indicator, time_str, time_type) 完全匹配去重
        """
        key = (indicator, time_str, time_type)
        for n in self.nodes:
            _, ind, t, tt = n
            if (ind, t, tt) == (indicator, time_str, time_type):
                logger.debug("add_node: 节点已存在，返回已有 id")
                return n[0]

        nid = self._new_id("n")
        self.nodes.append((nid, indicator, time_str, time_type))
        self._add_indicator_index(indicator)
        self._add_time_index(time_str, time_type)
        logger.info("🆕 ContextGraph.add_node: id=%s indicator=%s time=%s type=%s", nid, indicator, time_str, time_type)
        return nid

    def update_node(self, old_indicator: str, new_indicator: str):
        """
        当 pipeline 最终将某个临时指标替换为最终指标时调用：
        - 用 new_indicator 替换 nodes 中所有 old_indicator
        - 同步更新 indicators 索引
        """
        logger.info("ContextGraph.update_node: old=%s -> new=%s", old_indicator, new_indicator)
        updated_nodes = []
        for node in self.nodes:
            nid, indicator, t_str, t_type = node
            if indicator == old_indicator:
                updated_nodes.append((nid, new_indicator, t_str, t_type))
            else:
                updated_nodes.append(node)
        self.nodes = updated_nodes

        if old_indicator in self.indicators:
            try:
                self.indicators.remove(old_indicator)
            except ValueError:
                pass
        if new_indicator and new_indicator not in self.indicators:
            self.indicators.append(new_indicator)

    def find_node(self, indicator: Optional[str] = None, timeString: Optional[str] = None, timeType: Optional[str] = None) -> Optional[str]:
        """
        查找匹配节点：
        - 完全匹配 (indicator,timeString,timeType) 优先
        - 可支持单字段模糊匹配（只按提供的字段进行匹配）
        - 返回第一个匹配的节点 id 或 None
        """
        for nid, ind, t, tt in self.nodes:
            if indicator and ind != indicator:
                continue
            if timeString and t != timeString:
                continue
            if timeType and tt != timeType:
                continue
            return nid
        return None

    def get_node(self, node_id: str) -> Optional[Dict]:
        for nid, ind, t, tt in self.nodes:
            if nid == node_id:
                return {"id": nid, "indicator": ind, "timeString": t, "timeType": tt}
        return None

    # ---------------------
    # relations 操作
    # ---------------------
    def add_relation(self, rel_type: str, source: Tuple[str, Optional[str], Optional[str]] = None, target: Tuple[str, Optional[str], Optional[str]] = None, source_id: Optional[str] = None, target_id: Optional[str] = None, meta: Optional[Dict] = None) -> Optional[str]:
        """
        添加关系：
        - 可以传入 (source_id, target_id) 或者 source/target tuple (indicator,timeString,timeType)
        - 返回 relation id
        """
        if meta is None:
            meta = {}

        # resolve ids
        s_id = source_id
        t_id = target_id

        if not s_id and source:
            # source tuple -> find node
            s_id = self.find_node(indicator=source[0], timeString=source[1], timeType=source[2])
        if not t_id and target:
            t_id = self.find_node(indicator=target[0], timeString=target[1], timeType=target[2])

        if not s_id or not t_id:
            logger.warning("add_relation: 无法解析 source/target -> source_id=%s target_id=%s", s_id, t_id)
            return None

        # de-duplicate
        for r in self.relations:
            if r["type"] == rel_type and r["source"] == s_id and r["target"] == t_id:
                logger.debug("add_relation: 关系已存在")
                return r["id"]

        rid = f"r{uuid.uuid4().hex[:8]}"
        rel = {"id": rid, "type": rel_type, "source": s_id, "target": t_id, "meta": meta}
        self.relations.append(rel)
        logger.info("🔗 ContextGraph.add_relation: id=%s type=%s %s -> %s", rid, rel_type, s_id, t_id)
        return rid

    def get_relations(self, rel_type: Optional[str] = None) -> List[Dict]:
        if rel_type:
            return [r for r in self.relations if r["type"] == rel_type]
        return list(self.relations)

    # ---------------------
    # 智能解析 compare nodes（供 intent_router 调用）
    # ---------------------
    def resolve_compare_nodes(self, user_input: str = "", fallback_last_n: int = 2) -> Optional[Tuple[str, str]]:
        """
        解析想要对比的两个节点：
        - 优先解析用户输入中显式的时间或指标（简单正则）
        - 若无法解析，fallback 使用最近 N 个节点（默认最近 2 条）
        返回 (source_id, target_id) 或 None
        """
        logger.debug("resolve_compare_nodes: 尝试从输入解析对比目标: %s", user_input)

        # 1) try match explicit years/dates like "2020" / "2025-11" / "2025-11-04"
        years = re.findall(r"20\d{2}(?:[-/]\d{1,2}(?:[-/]\d{1,2})?)?", user_input)
        if len(years) >= 2:
            # try to find exact nodes by timeString
            src = self.find_node(timeString=years[0])
            tgt = self.find_node(timeString=years[1])
            if src and tgt:
                logger.debug("resolve_compare_nodes: 通过年份匹配到节点: %s , %s", src, tgt)
                return src, tgt

        # 2) try patterns like "上月", "上周", "昨天", "前天" - we won't expand them here,
        #    higher层（intent_router）应把这种自然语言解析为 concrete timeString via parse_user_input / time parser.
        #    So here we only do fallback based on available nodes.

        # 3) If nothing explicit, use last N nodes
        if len(self.nodes) >= fallback_last_n:
            src = self.nodes[-fallback_last_n][0]
            tgt = self.nodes[-1][0]
            logger.debug("resolve_compare_nodes: fallback 最近 %d 条节点: %s -> %s", fallback_last_n, src, tgt)
            return src, tgt

        logger.debug("resolve_compare_nodes: 无法解析对比节点")
        return None

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
# 用户上下文管理器（可选）
# =========================
class ContextManager:
    """
    管理每个 user_id 的 query 历史和 context_graph（灰度用，pipeline 里已有类似实现）
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
