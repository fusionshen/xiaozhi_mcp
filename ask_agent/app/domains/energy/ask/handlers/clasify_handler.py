# app/domain/energy/ask/handlers/clarify_handler.py
import logging
from app import core
from .common import _load_or_init_indicator, _resolve_formula, _execute_query, _finish, _is_reselect_intent, _handle_formula_choice
from .. import reply_templates
from .compare_handler import handle_compare
from .list_query_handler import handle_list_query   
from .analysis_handler import handle_analysis

logger = logging.getLogger("energy.ask.handlers.clarify")
if not logger.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )

# ------------------------- clarify 选择备选项 -------------------------
async def handle_clarify(
        user_id: str, 
        user_input: str, 
        graph: core.ContextGraph,
        current_intent: dict | None = None
):
    """
    基础能源查询：
    - 选择备选
    - 调用 formula_api 查询公式
    - 自动选择公式或提示候选
    - 执行平台查询
    - 成功查询节点写入 graph.nodes，保留当时 intent_info
    """
    logger.info("✅ [clarify] enter | user_input=%s", user_input)
    user_input = str(user_input or "").strip()
    # ==== 1. 加载意图状态 ====
    intent_info = graph.ensure_intent_info() or {}
    intent_info.setdefault("user_input_list", []).append(user_input)
    intent_info.setdefault("intent_list", []).append("clarify")
    # ==== 2. 判断是否为重选场景 ====
    is_reselect = _is_reselect_intent(intent_info, user_input)
    logger.info(f"🔄 clarify 重选判定: is_reselect={is_reselect}")
    # ==== 3. 加载 indicator（若是重选，不直接 append 新 active） ====
    # 如果是重选，我们不希望 _load_or_init_indicator 把 "重选 2" 等临时 active 写入 intent_info.indicators
    current = _load_or_init_indicator(intent_info, graph, allow_append=not is_reselect)
    # ==== 3. 如果是数字，则尝试选择候选公式，如果使用大模型判断，假如在有备选列表情况下，用户完整输入某个指标名称，user_input不是数字，也会是clarify ====
    reply, human_reply, done = _handle_formula_choice(current, user_input, graph, is_reselect, current_intent)
    if not done:
        # 说明还需要用户继续选择
        return _finish(user_id, graph, user_input, intent_info, reply, human_reply)
    # ==== 4. 若公式未确定，调用 _resolve_formula ====
    if current["slot_status"]["formula"] != "filled":
        reply, human_reply = await _resolve_formula(current, graph)
        if reply:
            # “请选择…” 或 “未找到公式” 之类的提示
            return _finish(user_id, graph, user_input, intent_info, reply, human_reply)

    # 时间 slot 判断
    current["slot_status"]["time"] = (
        "filled" if current.get("timeString") and current.get("timeType") else "missing"
    )

    # ==== 5. 若时间未填写 ====
    if current["slot_status"]["time"] != "filled":
        reply = f"好的，要查【{current['indicator']}】，请告诉我时间。"
        human_reply = reply_templates.reply_ask_time(current['indicator'])
        current["note"] = reply
        return _finish(user_id, graph, user_input, intent_info, reply, human_reply)
    
    # ==== 6. 公式 + 时间都有，执行查询 ====
    reply, human_reply, done = await _execute_query(current)
    if not done:
        return _finish(user_id, graph, user_input, intent_info, reply, human_reply)
    current["status"] = "completed"
    # 保存 intent_info
    graph.set_intent_info(intent_info)
    # 写入 node
    graph.add_node(current)
    # ==== 7. 判断 compare / list_query 是否继续 ====
    main_intent = graph.get_main_intent() or None
    if main_intent == "compare":
        logger.info("🔄 clarify 完成并检测到 compare 上下文，继续执行 handle_compare...")
        # 连续判断需要找到当前intent中active的indicator，作为当前current_info传入即可
        current_intents = [
            ind.get("indicator")
            for ind in intent_info.get("indicators")
            if ind.get("status") == "active" and ind.get("indicator")
        ]
        return await handle_compare(
            user_id, 
            f"{user_input} -> system:完成 clarify 并检测到 compare 上下文，继续执行 handle_compare...", 
            graph, 
            current_intent={"candidates": current_intents}
        )

    if main_intent == "list_query":
        logger.info("🔄 clarify 完成并检测到 list_query 上下文，继续执行 handle_list_query...")
        return await handle_list_query(
            user_id, 
            f"{user_input} -> system:完成 clarify 并检测到 list_query 上下文，继续执行 handle_list_query...", 
            graph
        )

    if main_intent == "analysis":
        logger.info("🔄 clarify 完成并检测到 analysis 上下文，继续执行 handle_analysis...")
        return await handle_analysis(
            user_id,
            f"{user_input} -> system:完成 clarify 并检测到 analysis 上下文，继续执行 handle_analysis...",
            graph
        )
    
    # ==== 8. 单查询完成，重置 intent ====
    return _finish(user_id, graph, user_input, {}, reply, human_reply)