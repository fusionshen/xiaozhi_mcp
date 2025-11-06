# core/pipeline.py

import asyncio
import logging
from core.context_graph import ContextGraph
from core.llm_energy_indicator_parser import parse_user_input
from agent_state import get_state, update_state, default_slots
from core.pipeline_handlers import (
    handle_new_query, handle_compare, handle_expand,
    handle_same_indicator_new_time, handle_list_query
)
from core.pipeline_context import get_graph, set_graph  # ✅ 新增

logger = logging.getLogger("pipeline")
if not logger.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )

async def process_message(user_id: str, message: str, graph_state_dict: dict):
    """能源语义查询主入口：根据 intent 分流处理"""
    user_input = (message or "").strip()
    logger.info(f"🟢 [process_message] user={user_id!r} input={user_input!r}")

    # 1️⃣ 加载 graph 和 slots
    graph = get_graph(user_id) or ContextGraph.from_state(graph_state_dict)
    set_graph(user_id, graph)  # ✅ 确保缓存同步
    
    session_state = await get_state(user_id)
    session_state.setdefault("slots", default_slots())
    slots = session_state["slots"]
    intent = slots.get("intent", "new_query")
    logger.info(f"🚦 检测到意图: {intent}")

    # ---------- 根据 intent 调用分支 ----------
    if intent == "compare":
        return await handle_compare(user_id, message, graph)
    elif intent == "expand":
        return await handle_expand(user_id, message, graph)
    elif intent == "same_indicator_new_time":
        return await handle_same_indicator_new_time(user_id, message, graph)
    elif intent == "list_query":
        return await handle_list_query(user_id, message, graph)
    else:
        return await handle_new_query(user_id, message, graph)
