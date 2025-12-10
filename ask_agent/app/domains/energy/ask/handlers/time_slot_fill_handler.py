# app/domain/energy/ask/handlers/time_slot_fill_handler.py
import logging
from app import core
from app.domains import energy as energy_domain
from .common import _resolve_formula, _execute_query, _finish
from .. import reply_templates
from .compare_handler import handle_compare
from .list_query_handler import handle_list_query   
from .analysis_handler import handle_analysis


logger = logging.getLogger("energy.ask.handlers.time_slot_fill")
if not logger.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )

# ------------------------- Slot 填充 基本属于时间-------------------------
async def handle_slot_fill(
    user_id: str,
    user_input: str,
    graph: core.ContextGraph,
    current_intent: dict | None = None
):
    """
    批量时间槽位补全逻辑：
    1. 找出所有 active 的指标
    2. 解析用户输入（时间）
    3. 如果没有或多条时间 → 提示重新输入
    4. 为每个 active 指标补全时间并执行查询
    5. 汇总结果，写入 graph
    """
    logger.info("🔁 [slot_fill] enter | user_input=%s", user_input)
    user_input = str(user_input or "").strip()
    # ----------------------------
    # step 0: intent info
    # 因为查询成功会清空当前intent_info，所以在成功查询一次后，后续问“那昨天的呢？”，会从最近的node中拉取snapshot
    # ----------------------------
    intent_info = graph.ensure_intent_info() or {}
    intent_info.setdefault("user_input_list", []).append(user_input)
    intent_info.setdefault("intent_list", []).append("slot_fill") 
    indicators = intent_info.setdefault("indicators", [])
    
    # ----------------------------
    # step 1: 解析时间
    # ----------------------------
    try:
        candidates = current_intent.get("candidates", [])
        if not candidates or len(candidates) != 1:
            reply = "抱歉，我不确定您指的时间，请重新输入（例如：昨天、上月、2024年10月）。"
            return _finish(user_id, graph, user_input, intent_info, reply, reply_templates.reply_ask_time_unknown())

        parsed = await energy_domain.llm.parse_user_input(candidates[0])
        logger.info("📌 slot_fill 时间解析结果: %s", parsed)
    except Exception as e:
        reply = f"解析时间失败: {e}"
        return _finish(user_id, graph, user_input, intent_info, reply, reply_templates.reply_time_parse_error())
    
    # ----------------------------
    # step 1.1 新增：如果解析到时间，但目前没有指标 → 保存 pending_time
    # ----------------------------
    has_time = parsed.get("timeString") and parsed.get("timeType")
    if has_time:
        intent_info["pending_time"] = {
            "timeString": parsed["timeString"],
            "timeType": parsed["timeType"]
        }
        logger.info(f"💾 已缓存 pending_time: {intent_info['pending_time']}")

    # ----------------------------
    # step 2: 找 active 指标
    # ----------------------------
    active_inds = [i for i in indicators if i.get("status") == "active"]
    if not active_inds:
        active_inds = indicators
    if not active_inds:
        # NONE → 无法继续
        reply = "请先告诉我要查询哪个指标。"
        return _finish(user_id, graph, user_input, intent_info, reply, reply_templates.reply_ask_indicator())

    # ----------------------------
    # step 2.1 新增：为所有 active 指标继承 pending_time
    # ----------------------------
    if "pending_time" in intent_info:
        pending = intent_info["pending_time"]
        for ind in active_inds:
            if not ind.get("timeString"):
                ind["timeString"] = pending["timeString"]
            if not ind.get("timeType"):
                ind["timeType"] = pending["timeType"]

            ind["slot_status"]["time"] = "filled"
        logger.info(f"⏳ active 指标继承 pending_time: {pending}")

    # ----------------------------
    # step 3: 批量为每个 active 指标补时间并查询
    # ----------------------------
    entries_results = []

    for ind in active_inds:
        # --- 3.1 再次写入当前解析的时间（以最新输入覆盖 pending）
        if has_time:
            ind["timeString"] = parsed.get("timeString")
            ind["timeType"] = parsed.get("timeType")
            ind["slot_status"]["time"] = "filled"

        # --- 3.2 补公式（复用 single_query 的流程） ---
        formula_reply, human_reply_formula = await _resolve_formula(ind, graph)
        if formula_reply:
            # 缺公式 → 返回候选列表
            return _finish(
                user_id,
                graph,
                user_input,
                intent_info,
                formula_reply,
                human_reply_formula
            )
        # --- 3.3 执行平台查询 ---
        if ind["slot_status"]["time"] == "filled":
            reply, human_reply, done = await _execute_query(ind)
            if not done:
                return _finish(user_id, graph, user_input, intent_info, reply, human_reply)
            ind["status"] = "completed"
            graph.add_node(ind)
            entries_results.append(ind)
        else:
            ind["note"] = f"❗ 指标【{ind.get('indicator')}】缺少时间信息"
            return _finish(user_id, graph, user_input, intent_info, ind["note"], reply_templates.reply_ask_indicator(ind.get('indicator')))
    # ----------------------------
    # step 4: 意图跳转 compare / list_query
    # ----------------------------
    main_intent = graph.get_main_intent() or None
    if main_intent == "compare":
        logger.info("🔄 solt_fill 完成并检测到 compare 上下文，继续执行 handle_compare...")
        return await handle_compare(
            user_id, 
            f"{user_input} -> system:完成 solt_fill 并检测到 compare 上下文，继续执行 handle_compare...", 
            graph
        )
    
    if main_intent == "list_query":
        logger.info("🔄 solt_fill 完成并检测到 list_query 上下文，继续执行 handle_list_query...")
        return await handle_list_query(
            user_id, 
            f"{user_input} -> system:完成 solt_fill 并检测到 list_query 上下文，继续执行 handle_list_query...", 
            graph
        )
    if main_intent == "analysis":
        logger.info("🔄 solt_fill 完成并检测到 analysis 上下文，继续执行 handle_analysis...")
        return await handle_analysis(
            user_id,
            f"{user_input} -> system:完成 solt_fill 并检测到 analysis 上下文，继续执行 handle_analysis...",
            graph
        )
    # ----------------------------
    # step 5: 正常结束
    # ----------------------------
    # 必须在清空意图前更新图谱
    graph.set_intent_info(intent_info)
    core.set_graph(user_id, graph)
    machine_reply = "\n".join(item.get("note", "").strip() for item in entries_results if item.get("note")) or "没有成功的查询结果。"
    logger.info(f"📊 slot_fill 汇总结果: {machine_reply}")
    # 成功查询后重置 intent（保持习惯）
    return _finish(user_id, graph, user_input, {}, machine_reply, reply_templates.reply_success_list(entries_results))