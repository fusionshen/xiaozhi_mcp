# app/domains/energy/ask/handlers/list_query_handler.py
import logging
from app import core
from app.domains import energy as energy_domain
from .common import _resolve_formula, _execute_query, _finish
from .. import reply_templates

logger = logging.getLogger("energy.ask.handlers.list_query")
if not logger.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )

# ------------------------- 批量查询 -------------------------
async def handle_list_query(
        user_id: str, 
        user_input: str, 
        graph: core.ContextGraph, 
        current_intent: dict | None = None
):
    """
    list_query 逻辑重构：
    - 完整复用 _resolve_formula / _execute_query / _finish
    - 支持多指标并行
    - 支持 beautify markdown 输出
    - 逻辑更清晰：按槽位依次补齐 → 执行 → 成功重置意图
    """
    logger.info("✅ [list_query] enter | user_input=%s", user_input)
    user_input = str(user_input or "").strip()
    # --- 初始化 intent_info ---
    intent_info = graph.get_intent_info() or {}
    intent_info.setdefault("user_input_list", []).append(user_input)
    intent_info.setdefault("intent_list", []).append("list_query")
    graph.set_main_intent("list_query")
    indicators = intent_info.setdefault("indicators", [])

    # --- llm 指标扩展 ---
    last_indicator_entry = (graph.get_last_completed_node() or {}).get("indicator_entry")
    current_intent = await energy_domain.llm.expand_indicator_candidates(last_indicator_entry, current_intent)

    # --- Slot-fill 情况：无 candidates，则保持原 indicators ---
    candidates = (current_intent or {}).get("candidates") or []

    # -------------------------------------------------------
    # ① 若没有 candidates → 视为 slot_fill（不改 indicators）
    # -------------------------------------------------------
    if not candidates:
        logger.info("ℹ️ current_intent 无 candidates，因此不修改现有 indicators（slot_fill 情况）。")
    else:
        # -------------------------------------------------------
        # ② 有 candidates → 解析并覆盖 active indicators
        # -------------------------------------------------------
        logger.info("🆕 解析 candidates，替换 active 指标列表")

        # 1) 保留 completed 的，删除 active 的
        kept = [item for item in indicators if item.get("status") != "active"]
        parsed = []

        # 2) 解析新的 candidates 为 active
        for c in candidates:
            entry = core.default_indicators()
            entry["status"] = "active"

            try:
                parsed_res = await energy_domain.llm.parse_user_input(c)
                for key in ("indicator", "formula", "timeString", "timeType"):
                    if parsed_res.get(key):
                        entry[key] = parsed_res[key]
            except Exception as e:
                logger.warning("parse_user_input 解析失败: %s → %s", c, e)
        
            # 自动补时间槽
            if entry.get("timeString") and entry.get("timeType"):
                entry["slot_status"]["time"] = "filled"

            parsed.append(entry)

        indicators = kept + parsed
        intent_info["indicators"] = indicators

    # -------------------------------------------------------
    # ③ 针对每个 indicator entry 开始补槽
    # -------------------------------------------------------
    entries_results = []
    for entry in indicators:
        # 3.1 缺指标
        if not entry.get("indicator"):
            reply = "请告诉我您要查询的每个指标名称。"
            return _finish(user_id, graph, user_input, intent_info, reply, reply_templates.reply_ask_indicator())
        
        # 3.2 补齐时间
        if entry["slot_status"]["time"] != "filled":
            reply = f"我不太确定您查询时间范围，请告诉我您要查询的具体时间。"
            return _finish(user_id, graph, user_input, intent_info, reply, reply_templates.reply_ask_time_unknown())
            
        # 3.3 解析公式
        reply, human_reply = await _resolve_formula(entry, graph)
        if reply:
            # 需要用户选择公式
            return _finish(user_id, graph, user_input, intent_info, reply, human_reply)
        
        # 3.4 查询缓存节点
        nid = graph.find_node(entry["indicator"], entry["timeString"])
        if nid:
            node = graph.get_node(nid)
            ie = node.get("indicator_entry", {})
            entry["value"] = ie.get("value")
            entry["note"] = ie.get("note")
            entry["status"] = "completed"
            entries_results.append(entry)
            continue

        # 3.5 平台查询
        reply, human_reply, done = await _execute_query(entry)
        if not done:
            return _finish(user_id, graph, user_input, intent_info, reply, human_reply)
        entry["status"] = "completed"
        graph.set_intent_info(intent_info)
        graph.add_node(entry)
        entries_results.append(entry)
    # -------------------------------------------------------
    # ④ 所有指标完成 → 写关系、输出回复
    # -------------------------------------------------------
    logger.info("🟦 所有指标已完成 batch 查询 (%s 个)", len(entries_results))

    # 1) 从每个 entry 取 note（保证非 None 并去除两端空白）
    # 2) 拼接成一个最终字符串（每个指标之间用两个换行或分隔线更易读）
    machine_reply = "\n".join(item.get("note", "").strip() for item in entries_results if item.get("note")) or "没有成功的查询结果。"
    # 写 group 关系
    sids = [graph.find_node(item["indicator"],item["timeString"]) for item in entries_results ]
    
    # write relation and history
    graph.add_relation("group", 
                       meta={
                           "via": "pipeline.list.query", 
                           "user_input": intent_info.get("user_input_list"), 
                           "ids": sids, 
                           "result": machine_reply
                        }
                    )
    logger.info("✅ list query 完成")
    # 成功查询重置意图
    return _finish(user_id, graph, user_input, {}, machine_reply, reply_templates.reply_success_list(entries_results))