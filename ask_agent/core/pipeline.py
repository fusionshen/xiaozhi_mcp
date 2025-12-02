# core/pipeline.py
import logging
from core.context_graph import ContextGraph
from core.pipeline_handlers import (
    handle_single_query, handle_compare, handle_analysis,
    handle_slot_fill, handle_list_query, handle_clarify
)
from core.pipeline_context import get_graph, set_graph

logger = logging.getLogger("pipeline")
if not logger.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )

async def process_message(user_id: str, user_input: str, current_intent: dict | None = None):
    """
    主流程入口：
    - 获取用户 ContextGraph
    - 根据 intent 分流到各 pipeline_handler
    """
    user_input = str(user_input or "").strip()
    logger.info(f"🟢 [process_message] user={user_id!r} input={user_input!r}")

    # 获取 graph
    graph = get_graph(user_id)
    if not graph:
        graph = ContextGraph()
        set_graph(user_id, graph)
        logger.info("✨ 创建新的 ContextGraph")

    # 当前意图信息
    last_intent_info = graph.get_intent_info()
    intent = current_intent.get("intent", "single_query")
    logger.info(f"🚦 当前 intent={intent}，系统保留 intent={last_intent_info.get("intent")}")

    # ---------- 根据 intent 调用分支 ----------
    if intent == "compare":
        return await handle_compare(user_id, user_input, graph, current_intent)
    elif intent == "analysis":
        return await handle_analysis(user_id, user_input, graph)
    elif intent == "slot_fill":
        return await handle_slot_fill(user_id, user_input, graph, current_intent)
    elif intent == "list_query":
        return await handle_list_query(user_id, user_input, graph, current_intent)
    elif intent == "clarify":
        return await handle_clarify(user_id, user_input, graph, current_intent)
    else:
        return await handle_single_query(user_id, user_input, graph)
