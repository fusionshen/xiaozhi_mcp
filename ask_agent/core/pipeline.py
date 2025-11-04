# core/pipeline.py
import asyncio
import logging
import inspect
from core.context_graph import ContextGraph
from core.llm_energy_indicator_parser import parse_user_input
from tools import formula_api, platform_api
from agent_state import get_state, update_state

logger = logging.getLogger("pipeline")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")

TOP_N = 5

# 内存缓存：每个用户的上下文图谱（session -> ContextGraph）
graph_store = {}


async def process_message(user_id: str, message: str, graph_state_dict: dict):
    """
    用户消息处理管线：
      1) 加载 slots 状态与上下文图谱（graph）
      2) 用户选择候选公式或调用 LLM 解析 indicator/time
      3) 缺失信息引导用户补全
      4) formula_api 查询公式（精确/候选/自动选择）
      5) 执行查询 platform_api 并更新 graph/history
    """
    user_input = (message or "").strip()
    logger.info(f"🟢 [process_message] user={user_id!r} input={user_input!r}")

    # 1️⃣ 加载 graph 和 slots
    graph = graph_store.setdefault(user_id, ContextGraph.from_state(graph_state_dict))
    session_state = await get_state(user_id)
    session_state.setdefault("slots", _default_slots())
    slots = session_state["slots"]

    logger.info(f"当前 slots (before parsing): {slots}")

    # 2️⃣ 用户选择候选公式（数字输入）
    if slots.get("formula_candidates") and user_input.isdigit():
        idx = int(user_input.strip()) - 1
        candidates = slots["formula_candidates"]
        logger.info("检测到用户在选择候选公式（digit input） index=%s, candidates_count=%d", idx, len(candidates))
        if 0 <= idx < len(candidates):
            chosen = candidates[idx]
            slots["formula"] = chosen["FORMULAID"]
            slots["indicator"] = chosen["FORMULANAME"]
            slots["formula_candidates"] = None
            slots["awaiting_confirmation"] = False
            await update_state(user_id, session_state)
            logger.info("✅ 用户选择公式: %s (FORMULAID=%s, score=%s)",
                        chosen.get("FORMULANAME"), chosen.get("FORMULAID"), chosen.get("score"))

            # 如果缺时间，提示补全
            if not (slots.get("timeString") and slots.get("timeType")):
                return f"好的，要查【{slots['indicator']}】，请告诉我时间。", graph.to_state()

            # 否则执行查询
            return await _execute_query(user_id, slots, graph)
        else:
            logger.warning("⚠️ 用户输入的候选编号超范围: %s", user_input)
            return f"请输入编号 1~{len(candidates)} 选择公式。", graph.to_state()

    # 3️⃣ 非数字输入且存在候选 => 清空候选重新解析
    if slots.get("formula_candidates"):
        logger.info("🧩 非数字输入且存在候选，清空候选并重新解析输入。")
        slots["formula_candidates"] = None
        slots["formula"] = None
        await update_state(user_id, session_state)

    # 4️⃣ 调用 LLM 解析补全 indicator/time 并增强 intent
    try:
        parsed = await parse_user_input(user_input)
        logger.info("🔍 LLM 解析结果: %s", parsed)
    except Exception as e:
        logger.exception("❌ parse_user_input 调用失败: %s", e)
        parsed = {"indicator": None, "timeString": None, "timeType": None}

    # 合并 slots（仅补全缺失信息，不覆盖已有）
    for k in ("indicator", "timeString", "timeType"):
        if parsed.get(k):
            slots[k] = parsed.get(k)
            logger.debug("补全 slots: %s -> %s", k, parsed.get(k))

    # ✅ 多轮增强 intent（同时写入 slots["intent"]）
    last_indicator = None
    history = session_state.get("history", [])
    if history:
        for h in reversed(history):
            if h.get("indicator"):
                last_indicator = h["indicator"]
                break

    from core.llm_energy_intent_parser import EnergyIntentParser
    parser = EnergyIntentParser(user_id)
    enhanced_intent = parser._enhance_intent_by_keywords(slots.get("intent", "new_query"), user_input, last_indicator)
    slots["intent"] = enhanced_intent
    logger.info(f"🎯 slots['intent'] 已设置为: {enhanced_intent}")

    await update_state(user_id, session_state)
    logger.info("当前 slots (after parsing): %s", slots)

    # 5️⃣ 如果 indicator 缺失，询问用户提供指标
    if not slots.get("indicator"):
        logger.info("⚠️ indicator 缺失，要求用户补全指标名称。")
        return "请告诉我您要查询的指标名称。", graph.to_state()

    # 6️⃣ 使用 formula_api 查找公式
    logger.info("🔎 调用 formula_api.formula_query_dict 查询公式, indicator=%s", slots["indicator"])
    try:
        formula_resp = await asyncio.to_thread(formula_api.formula_query_dict, slots["indicator"])
    except Exception as e:
        logger.exception("❌ 调用 formula_api 失败: %s", e)
        return f"查找公式时出错: {e}", graph.to_state()

    logger.info("formula_api 返回摘要: done=%s, exact_matches=%s, candidates_len=%s",
                formula_resp.get("done"), bool(formula_resp.get("exact_matches")), len(formula_resp.get("candidates", [])))
    exact_matches = formula_resp.get("exact_matches") or []
    candidates = formula_resp.get("candidates") or []

    if exact_matches:
        chosen = exact_matches[0]
        slots["formula"] = chosen["FORMULAID"]
        slots["indicator"] = chosen["FORMULANAME"]
        await update_state(user_id, session_state)
        logger.info("✅ 精确匹配公式: %s (FORMULAID=%s)", slots["indicator"], slots["formula"])

        # 如果没有时间，询问时间
        if not (slots.get("timeString") and slots.get("timeType")):
            return f"好的，要查【{slots['indicator']}】，请告诉我时间。", graph.to_state()

        # 完整 -> 执行查询
        return await _execute_query(user_id, slots, graph)
    # 有候选但没有精确匹配
    if candidates:
        logger.info("🔢 找到 %d 个候选公式（按 score 排序）", len(candidates))
        top = candidates[0]
        logger.info("🔢 找到 %d 个候选公式, 最高候选: %s (score=%s)", len(candidates), top.get("FORMULANAME"), top.get("score"))
        if top.get("score", 0) > 100:
            chosen = top
            slots["formula"] = chosen["FORMULAID"]
            slots["indicator"] = chosen["FORMULANAME"]
            slots["formula_candidates"] = None
            await update_state(user_id, session_state)
            logger.info("🧠 自动选择高分候选公式: %s (score=%s)", chosen.get("FORMULANAME"), chosen.get("score"))

            if not (slots.get("timeString") and slots.get("timeType")):
                return f"好的，要查【{slots['indicator']}】，请告诉我时间。", graph.to_state()
            # 否则执行查询
            return await _execute_query(user_id, slots, graph)
        # 否则展示候选并等待用户选择
        slots["formula_candidates"] = candidates[:TOP_N]
        await update_state(user_id, session_state)
        msg_lines = ["请从以下候选公式选择编号："]
        for idx, c in enumerate(candidates[:TOP_N], 1):
            msg_lines.append(f"{idx}) {c['FORMULANAME']} (score {c.get('score',0):.2f})")
        logger.info("➡️ 返回候选列表供用户选择（count=%d）", len(slots["formula_candidates"]))
        return "\n".join(msg_lines), graph.to_state()

    logger.info("❌ 未找到匹配公式: indicator=%s", slots["indicator"])
    return "未找到匹配公式，请重新输入指标名称。", graph.to_state()


async def _execute_query(user_id: str, slots: dict, graph: ContextGraph):
    try:
        formula = slots.get("formula")
        indicator = slots.get("indicator")
        time_str = slots.get("timeString")
        time_type = slots.get("timeType")

        # 调用 platform_api 获取结果
        if inspect.iscoroutinefunction(platform_api.query_platform):
            result = await platform_api.query_platform(formula, time_str, time_type)
        else:
            result = await asyncio.to_thread(platform_api.query_platform, formula, time_str, time_type)

        logger.info("✅ platform_api 返回: %s", result)

        # 格式化结果
        if isinstance(result, dict):
            val = result.get(formula) or result.get("value") or next(iter(result.values()), None)
            unit = result.get("unit", "")
            reply = f"✅ {indicator} 在 {time_str} ({time_type}) 的值是 {val} {unit}"
        elif isinstance(result, list):
            lines = []
            for item in result:
                clock = item.get("clock") or item.get("timestamp") or item.get("time")
                val = item.get("itemValue") or item.get("value") or item.get("v")
                lines.append(f"{clock}: {val}")
            reply = f"✅ {indicator} 在 {time_str} ({time_type}) 的查询结果:\n" + "\n".join(lines)
        else:
            reply = f"✅ {indicator} 在 {time_str} ({time_type}) 的查询结果: {result}"

        # 更新 graph 节点
        state = await get_state(user_id)
        history = state.get("history", [])
        last_indicator = next((h["indicator"] for h in reversed(history) if h.get("indicator")), None)

        if last_indicator and last_indicator != indicator:
            graph.update_node(old_indicator=last_indicator, new_indicator=indicator)
        else:
            graph.add_node(indicator, time_str, time_type)

        # 自动处理 compare 意图关系
        if slots.get("intent") == "compare" and len(graph.nodes) >= 2:
            prev_node = graph.nodes[-2]
            curr_node = graph.nodes[-1]
            graph.add_relation("compare", prev_node, curr_node)

        graph_store[user_id] = graph

        # 写入 history
        state.setdefault("history", [])
        state["history"].append({
            "user_input": slots.get("last_input", ""),
            "indicator": indicator,
            "formula": formula,
            "timeString": time_str,
            "timeType": time_type,
            "result": reply,
            "intent": slots.get("intent", "new_query")
        })

        # 清理临时 slots
        slots["formula_candidates"] = None
        slots["awaiting_confirmation"] = False
        await update_state(user_id, state)

        return reply, graph.to_state()
    except Exception as e:
        logger.exception("❌ 执行查询时出错: %s", e)
        return f"查询时出错: {e}", graph.to_state()


def _default_slots():
    return {
        "indicator": None,
        "formula": None,
        "formula_candidates": None,
        "awaiting_confirmation": False,
        "timeString": None,
        "timeType": None,
        "last_input": None,
        "intent": None
    }
