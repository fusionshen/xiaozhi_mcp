# app/domain/energy/ask/handlers/single_query_handler.py
import logging
from app.core.context_graph import ContextGraph
from app.domains import energy as energy_domain
from .common import _load_or_init_indicator, _resolve_formula, _execute_query, _finish
from .. import reply_templates
from .compare_handler import handle_compare
from .list_query_handler import handle_list_query   
from .analysis_handler import handle_analysis

logger = logging.getLogger("energy.ask.handlers.single_query")
if not logger.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )

# ------------------------- 单指标查询 -------------------------
async def handle_single_query(user_id: str, user_input: str, graph: ContextGraph):
    """
    单指标查询（重写版）：
        1. 加载或初始化 active indicator
        2. LLM 解析补全缺失 slot
        3. 查询 / 选择公式
        4. 若公式+时间齐全 → 执行平台查询
        5. 按 main_intent 进行 compare / list_query 跳转
        6. 所有分支使用统一出口，保证状态干净
    """
    logger.info("🔵 [single] enter | user_input=%s", user_input)
    user_input = str(user_input or "").strip()
    # ----------------------------
    # step 0 : 当前 intent 信息
    # ----------------------------
    intent_info = graph.ensure_intent_info()
    intent_info.setdefault("user_input_list", []).append(user_input)
    intent_info.setdefault("intent_list", []).append("single_query")
    # ----------------------------
    # step 1 : 获取 / 创建 active indicator
    # ----------------------------
    current = _load_or_init_indicator(intent_info, graph)
    logger.info("🔹 active indicator = %s", current.get("indicator"))
    # ----------------------------
    # step 2 : LLM 补齐指标/时间
    # ----------------------------
    try:
        parsed = await energy_domain.llm.parse_user_input(user_input)
        for key in ("indicator", "formula", "timeString", "timeType"):
            if parsed.get(key):
                current[key] = parsed[key]
    except Exception as e:
        logger.warning("⚠️ LLM 解析失败: %s", e)
    
    # 尝试从暂存中获取时间
    if not parsed.get("timeString") and not parsed.get("timeType"):
        pending = intent_info.get("pending_time")
        if pending:
            current["timeString"] = pending["timeString"]
            current["timeType"] = pending["timeType"]

    # 时间 slot 判断
    current["slot_status"]["time"] = (
        "filled" if current.get("timeString") and current.get("timeType") else "missing"
    )

    # 若缺少指标必须询问
    if not current.get("indicator"):
        return _finish(user_id, graph, user_input, intent_info, "请告诉我您要查询的指标名称。", reply_templates.reply_ask_indicator())
    # ----------------------------
    # step 3 : 公式选择
    # ----------------------------
    formula_reply, human_reply = await _resolve_formula(current, graph)
    if formula_reply:                                         # 用户需要手动选择
        return _finish(user_id, graph, user_input, intent_info, formula_reply, human_reply)
    # ----------------------------
    # step 4 : 若公式 & 时间齐全 → 执行平台查询
    # ----------------------------
    if current["slot_status"]["formula"] == "filled" and current["slot_status"]["time"] == "filled":
        reply, human_reply, done = await _execute_query(current)
        if not done:
            return _finish(user_id, graph, user_input, intent_info, reply, human_reply)
        current["status"] = "completed"
        # 必须在addNode前写入节点
        graph.set_intent_info(intent_info)
        graph.add_node(current)
        # ------------------------
        # step 5 : 按上下文跳转
        # ------------------------
        main_intent = graph.get_main_intent()
        if main_intent == "compare":
            logger.info("🔄 single query 完成并检测到 compare 上下文，继续执行 handle_compare...")
            current_intents = [
                ind.get("indicator")
                for ind in intent_info["indicators"]
                if ind.get("status") == "active" and ind.get("indicator")
            ]
            return await handle_compare(
                user_id,
                f"{user_input} -> system:完成 single query 并检测到 compare 上下文，继续执行 handle_single_query...",
                graph,
                current_intent={"candidates": current_intents}
            )

        if main_intent == "list_query":
            logger.info("🔄 single query 完成并检测到 list_query 上下文，继续执行 handle_list_query...")
            return await handle_list_query(
                user_id,
                f"{user_input} -> system:完成 single query 并检测到 list_query 上下文，继续执行 handle_list_query...",
                graph
            )
        
        if main_intent == "analysis":
            logger.info("🔄 single query 完成并检测到 analysis 上下文，继续执行 handle_analysis...")
            return await handle_analysis(
                user_id,
                f"{user_input} -> system:完成 single query 并检测到 analysis 上下文，继续执行 handle_analysis...",
                graph
            )
        return _finish(user_id, graph, user_input, {}, reply, human_reply)
    # ----------------------------
    # step 4.2 ：缺时间，继续询问
    # ----------------------------
    ask = f"好的，要查【{current['indicator']}】，请告诉我时间。"
    current["note"] = ask
    return _finish(user_id, graph, user_input, intent_info, ask, reply_templates.reply_ask_time(current['indicator']))
