# core/context_graph.py
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any
import logging
import copy

logger = logging.getLogger("context_graph")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")

@dataclass
class ContextGraph:
    """
    上下文语义图谱（轻量实现）：
    - nodes: 每个 node 包含当时查询成功的 indicator 数据与历史信息
    - relations: 关系，如 compare、sequence
    - meta: 临时/扩展信息
    """
    nodes: List[Dict[str, Any]] = field(default_factory=list)
    relations: List[Dict[str, Any]] = field(default_factory=list)
    meta: dict = field(default_factory=dict)
    _next_id: int = field(default=1, init=False, repr=False)

    # ---------------------
    # intent_info 管理（当前操作参考）
    # ---------------------
    def set_intent_info(self, intent_info: dict):
        self.meta["current_intent_info"] = intent_info

    def get_intent_info(self) -> dict:
        return self.meta.get("current_intent_info", {})
    
    def ensure_intent_info(self) -> dict:
        """
        确保 graph.meta.current_intent_info 存在：
        如果为空，则从最近 Node.intent_info_snapshot 中恢复
        """
        intent_info = self.get_intent_info() or {}
        # 如果当前为空，则尝试从最后一个 node 恢复
        if not intent_info:
            nodes = self.nodes
            if nodes:
                last_node = nodes[-1]
                snapshot = last_node.get("intent_info_snapshot")
                if snapshot:
                    intent_info = copy.deepcopy(snapshot)
                    self.set_intent_info(intent_info)
                    print("✅ 已从最近节点恢复 intent_info:", intent_info)
                else:
                    print("⚠️ 最近节点无 intent_info_snapshot")
            else:
                print("⚠️ 无节点可恢复 intent_info")

        return intent_info

    
    # ---------------------
    # history 管理
    # ---------------------
    def add_history(self, user_input: str, reply: str):
        hist = self.meta.setdefault("history", [])
        hist.append({"ask": user_input, "reply": reply})
        logger.info(f"🕘 add_history: {user_input} -> {reply}")

    def get_history(self) -> List[Dict[str, str]]:
        return self.meta.get("history", [])
    
    # ---------------------
    # 用户偏好管理
    # ---------------------
    def add_preference(self, user_indicator_input: str, formula_id: str, formula_name: str):
        prefs = self.meta.setdefault("preferences", {})
        prefs[user_indicator_input] = {
            "FORMULAID": formula_id,
            "FORMULANAME": formula_name
        }
        logger.info(f"💡 add_preference: '{user_indicator_input}' -> {formula_name} ({formula_id})")

    def get_preference(self, user_indicator_input: str) -> dict | None:
        prefs = self.meta.get("preferences", {})
        logger.info(f"🧩 从用户偏好恢复 {user_indicator_input} -> {prefs.get(user_indicator_input)}")
        return prefs.get(user_indicator_input)
    
    # ---------------------
    # clarify 重选时更新旧偏好
    # ---------------------
    def update_preference(self, current_indicator: str, matched: dict) -> bool:
        """
        clarify 重选时，根据 current["indicator"] 找到旧 preference，并更新为 matched。
        参数：
            current_indicator: 当前 需要替换的指标名称
            matched: 选中的公式候选项（包含 FORMULAID, FORMULANAME, number）
        返回：
            True - 成功更新
            False - 没找到匹配
        """
        prefs = self.meta.get("preferences", {})
        old_key = None

        for key, pref in prefs.items():
            if pref.get("FORMULANAME") == current_indicator:
                old_key = key
                break

        if old_key:
            prefs[old_key] = {
                "FORMULAID": matched["FORMULAID"],
                "FORMULANAME": matched["FORMULANAME"]
            }
            logger.info(f"🔄 clarify 重选偏好更新：{old_key} => {matched['FORMULANAME']}")
            return True

        return False

    # ---------------------
    # 总体意图管理
    # ---------------------
    def set_main_intent(self, intent: dict | str):
        self.meta["main_intent"] = intent
        logger.info(f"🎯 set_main_intent: {intent}")

    def get_main_intent(self) -> dict | str | None:
        return self.meta.get("main_intent")

    def clear_main_intent(self):
        if "main_intent" in self.meta:
            del self.meta["main_intent"]
            logger.info("🧹 main_intent cleared.")

    # ---------------------
    # 节点管理
    # ---------------------
    def _alloc_id(self) -> int:
        nid = self._next_id
        self._next_id += 1
        return nid

    def add_node(self, indicator_entry: dict) -> int:
        """
        添加成功查询节点，同时保存当时的 intent_info
        indicator_entry: 包含 id/formula/indicator/time/value/note/slot_status/formula_candidates
        """
        nid = self._alloc_id()
        node = {
            "id": nid,
            "indicator_entry": copy.deepcopy(indicator_entry),  # 保存当时 indicator
            "intent_info_snapshot": copy.deepcopy(self.get_intent_info())
        }
        self.nodes.append(node)
        logger.info("🆕 ContextGraph.add_node -> id=%s, indicator=%s, time=%s",
                    nid,
                    indicator_entry.get("indicator"),
                    indicator_entry.get("timeString"))
        return nid

    def find_node(self, indicator: Optional[str] = None, timeString: Optional[str] = None) -> Optional[int]:
        for n in self.nodes:
            e = n["indicator_entry"]
            if indicator is not None and timeString is not None:
                if e.get("indicator") == indicator and e.get("timeString") == timeString:
                    return n["id"]
            elif indicator is not None and timeString is None:
                if e.get("indicator") == indicator:
                    return n["id"]
        return None

    def get_node(self, node_id: int) -> Optional[Dict[str, Any]]:
        for n in self.nodes:
            if n["id"] == node_id:
                return n
        return None
    
    def get_last_completed_node(self):
        """获取最近一个已完成节点（status=completed）"""
        for node in reversed(self.nodes):
            entry = node.get("indicator_entry", {})
            if entry.get("status") == "completed":
                return node
        return None

    # ---------------------
    # 关系管理
    # ---------------------
    def add_relation(self, rel_type: str, source_id: Optional[int] = None, target_id: Optional[int] = None, meta: Optional[Dict] = None):
        rel = {"type": rel_type, "source": source_id, "target": target_id, "meta": meta or {}}
        if rel not in self.relations:
            self.relations.append(rel)
            logger.info("🔗 ContextGraph.add_relation: %s (source=%s target=%s) meta=%s",
                        rel_type, source_id, target_id, meta or {})
        else:
            logger.debug("🟡 relation already exists: %s", rel)

    def get_relations(self, rel_type: Optional[str] = None) -> List[Dict[str, Any]]:
        if rel_type:
            return [r for r in self.relations if r.get("type") == rel_type]
        return list(self.relations)

    # ---------------------
    # compare 辅助
    # ---------------------
    def resolve_compare_nodes(self) -> Optional[tuple[int, int]]:
        # 1) explicit compare
        for r in reversed(self.relations):
            if r.get("type") == "compare" and r.get("source") and r.get("target"):
                return r.get("source"), r.get("target")
        # 2) fallback to last two nodes
        if len(self.nodes) >= 2:
            return self.nodes[-2]["id"], self.nodes[-1]["id"]
        return None

    # ---------------------
    # 序列化
    # ---------------------
    def to_state(self) -> Dict[str, Any]:
        return {
            "graph": {
                "nodes": self.nodes,
                "relations": self.relations,
                "_next_id": self._next_id
            },
            "meta": self.meta
        }

    @classmethod
    def from_state(cls, state: Dict[str, Any]):
        g = cls()
        graph_data = state.get("graph", {}) if isinstance(state, dict) else {}
        g.nodes = graph_data.get("nodes", []) or []
        g.relations = graph_data.get("relations", []) or []
        g._next_id = graph_data.get("_next_id", max([n["id"] for n in g.nodes], default=0) + 1)
        g.meta = state.get("meta", {}) or {}
        return g


def default_indicators():
    return {
        "status": "active",
        "indicator": None,
        "formula": None,
        "timeString": None,
        "timeType": None,
        "slot_status": {"formula": "missing", "time": "missing"},
        "value": None,
        "note": None,
        "formula_candidates": None
    }