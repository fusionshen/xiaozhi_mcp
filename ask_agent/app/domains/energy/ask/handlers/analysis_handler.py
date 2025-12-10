# app/domains/energy/ask/handlers/analysis_handler.py
import logging
from app import core
from app.domains import energy as energy_domain
from .common import _resolve_formula, _execute_query, _finish
from .. import reply_templates

logger = logging.getLogger("energy.ask.handlers.analysis")
if not logger.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )

TOP_N = 5

# ------------------------- 趋势分析 -------------------------
async def handle_analysis(
        user_id: str, 
        message: str, 
        graph: core.ContextGraph,
        current_intent: dict | None = None
):
    """
    趋势分析主入口
    目标：当用户询问类似 "本年度的高炉工序能耗趋势是什么样的" 时：
      1. 解析指标与时间段（支持 timeString 如 "2025-01~2025-09" 或自然语言）
      2. 确保指标/公式解析正确（通过 _resolve_formula）
      3. 获取时间序列数据
      4. 绘制并保存趋势图
      5. 生成自动化分析结论（基本统计 + 方向/斜率说明）
    返回：_finish(...) 格式（reply, human_reply, state）
    """
    logger.info("📈 [analysis] enter | user=%s, input=%s", user_id, message)
    user_input = str(message or "").strip()
    # ensure intent_info
    intent_info = graph.get_intent_info() or {}
    intent_info.setdefault("user_input_list", []).append(user_input)
    intent_info.setdefault("intent_list", []).append("analysis")
    graph.set_main_intent("analysis")
    indicators = intent_info.setdefault("indicators", [])
    
    # --- LLM 指标扩展（复用） ---
    last_indicator_entry = (graph.get_last_completed_node() or {}).get("indicator_entry")
    current_intent = await energy_domain.llm.expand_indicator_candidates(last_indicator_entry, current_intent)
    # parse user input to find candidates (reuse same pattern as compare)
    candidates = (current_intent or {}).get("candidates") or []
    # -------------------------------------------------------
    # ① 若没有 candidates → 视为 slot_fill 或者 两步问趋势（不改 indicators）
    # -------------------------------------------------------
    if not candidates:
        logger.info("ℹ️ current_intent 无 candidates，因此不修改现有 indicators（slot_fill 或 two steps 情况）。")
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
            reply = f"我不太确定您查询时间范围，请告诉我您要查询的具体时间区间。"
            return _finish(user_id, graph, user_input, intent_info, reply, reply_templates.reply_ask_time_unknown())

        if not ("~" in entry.get("timeString", "")):
            # 对于趋势分析，时间段格式需要特殊处理
            # 对时间进行LLM区间增强
            parsed_range = await energy_domain.llm.normalize_time_range(entry.get("timeString"), entry.get("timeType"))
            if not ("~" in parsed_range.get("timeString", "")):
                reply = f"您提供的时间已经是最小粒度，无法提取用于趋势分析的时间范围。" 
                return _finish(user_id, graph, user_input, intent_info, reply, reply_templates.reply_time_range_normalized_error())  
            logger.info(f"🧩 时间区间增强：{entry.get("timeString")}({entry.get("timeType")}) -> {parsed_range.get("timeString")}({parsed_range.get("timeType")})")
            entry["timeString"] = parsed_range.get("timeString")
            entry["timeType"] = parsed_range.get("timeType")
            entry["slot_status"]["time"] = "filled"

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
    machine_reply = await energy_domain.llm.call_trend_llm(entries_results)
    # 写 group 关系
    sids = [graph.find_node(item["indicator"],item["timeString"]) for item in entries_results ]
    # write relation and history
    graph.add_relation("analysis", 
                       meta={
                           "via": "pipeline.analysis", 
                           "user_input": intent_info.get("user_input_list"), 
                           "ids": sids, 
                           "result": machine_reply
                        }
                    )
    logger.info("✅ analysis 完成")
    # 成功查询重置意图
    return _finish(user_id, graph, user_input, {}, machine_reply, reply_templates.reply_analysis(entries_results, machine_reply))

