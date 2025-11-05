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
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )

TOP_N = 5
graph_store = {}  # 每个用户的上下文图谱缓存


def _default_slots():
    """默认 slots 模板"""
    return {
        "indicator": None,
        "formula": None,
        "timeString": None,
        "timeType": None,
        "intent": "new_query",
        "formula_candidates": None,
        "awaiting_confirmation": False,
        "last_input": ""
    }


async def process_message(user_id: str, message: str, graph_state_dict: dict):
    """
    🧩 用户消息处理管线：
      1️⃣ 载入 slots 与上下文图谱
      2️⃣ 判断是否为候选公式选择
      3️⃣ 调用 LLM 解析指标与时间
      4️⃣ 查询公式（formula_api）
      5️⃣ 调用 platform_api 获取结果并更新图谱/历史
    """
    user_input = (message or "").strip()
    logger.info(f"🟢 [process_message] user={user_id!r} input={user_input!r}")

    # 1️⃣ 加载上下文
    graph = graph_store.setdefault(user_id, ContextGraph.from_state(graph_state_dict))
    session_state = await get_state(user_id)
    session_state.setdefault("slots", _default_slots())
    slots = session_state["slots"]

    logger.info(f"📦 当前 slots (before parsing): {slots}")

    # 2️⃣ 如果用户输入数字，尝试选择候选公式
    if slots.get("formula_candidates") and user_input.isdigit():
        idx = int(user_input.strip()) - 1
        candidates = slots["formula_candidates"]
        logger.info(f"🔢 检测到候选选择 index={idx}, count={len(candidates)}")
        if 0 <= idx < len(candidates):
            chosen = candidates[idx]
            slots["formula"] = chosen["FORMULAID"]
            slots["indicator"] = chosen["FORMULANAME"]
            slots["formula_candidates"] = None
            slots["awaiting_confirmation"] = False
            await update_state(user_id, session_state)
            logger.info(f"✅ 用户选择公式: {slots['indicator']} (FORMULAID={slots['formula']})")

            # 如果缺时间，提示补全
            if not (slots.get("timeString") and slots.get("timeType")):
                return f"好的，要查【{slots['indicator']}】，请告诉我时间。", graph.to_state()

            # 否则执行查询
            return await _execute_query(user_id, slots, graph)
        else:
            logger.warning("⚠️ 用户输入的候选编号超范围: %s", user_input)
            return f"请输入编号 1~{len(candidates)} 选择公式。", graph.to_state()

    # 3️⃣ 若输入非数字但存在候选，则清空并重新解析
    if slots.get("formula_candidates"):
        logger.info("🧩 清空旧候选，重新进入解析流程。")
        slots["formula_candidates"] = None
        slots["formula"] = None
        await update_state(user_id, session_state)

    # 4️⃣ 调用 LLM 解析 indicator / time
    try:
        parsed = await parse_user_input(user_input)
        logger.info(f"🔍 LLM 解析结果: {parsed}")
    except Exception as e:
        logger.exception("❌ parse_user_input 调用失败: %s", e)
        parsed = {}
    # 合并 slots（仅补全缺失信息，不覆盖已有）
    for key in ("indicator", "timeString", "timeType"):
        if parsed.get(key):
            slots[key] = parsed[key]
            logger.debug(f"🧩 补全 slots: {key}={parsed[key]}")

    await update_state(user_id, session_state)
    logger.info(f"📦 当前 slots (after parsing): {slots}")

    # 5️⃣ 如果指标缺失，要求用户补全
    if not slots.get("indicator"):
        logger.info("⚠️ 缺少 indicator，提示用户补全。")
        return "请告诉我您要查询的指标名称。", graph.to_state()

    # 6️⃣ 查找公式
    indicator = slots["indicator"]
    logger.info(f"🔎 调用 formula_api 查询公式: {indicator}")
    try:
        formula_resp = await asyncio.to_thread(formula_api.formula_query_dict, indicator)
    except Exception as e:
        logger.exception("❌ 调用 formula_api 失败: %s", e)
        return f"查找公式时出错: {e}", graph.to_state()

    exact_matches = formula_resp.get("exact_matches") or []
    candidates = formula_resp.get("candidates") or []
    logger.info(f"📊 formula_api 返回: exact={len(exact_matches)}, candidates={len(candidates)}")

    # 6A️⃣ 精确匹配
    if exact_matches:
        chosen = exact_matches[0]
        slots["formula"] = chosen["FORMULAID"]
        slots["indicator"] = chosen["FORMULANAME"]
        await update_state(user_id, session_state)
        logger.info(f"✅ 精确匹配公式: {slots['indicator']} (FORMULAID={slots['formula']})")

        # 如果没有时间，询问时间
        if not (slots.get("timeString") and slots.get("timeType")):
            return f"好的，要查【{slots['indicator']}】，请告诉我时间。", graph.to_state()

        # 完整 -> 执行查询
        return await _execute_query(user_id, slots, graph)

    # 6B️⃣ 候选匹配
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
            logger.info(f"🧠 自动选择高分候选公式: {slots['indicator']} (score={top['score']})")

            if not (slots.get("timeString") and slots.get("timeType")):
                return f"好的，要查【{slots['indicator']}】，请告诉我时间。", graph.to_state()
            # 否则执行查询
            return await _execute_query(user_id, slots, graph)
        else:
            slots["formula_candidates"] = candidates[:TOP_N]
            await update_state(user_id, session_state)
            msg_lines = ["请从以下候选公式选择编号："]
            for i, c in enumerate(candidates[:TOP_N], 1):
                msg_lines.append(f"{i}) {c['FORMULANAME']} (score {c.get('score', 0):.2f})")
            logger.info("➡️ 返回候选公式供用户选择")
            return "\n".join(msg_lines), graph.to_state()

    # 6C️⃣ 无匹配
    logger.info(f"❌ 未找到匹配公式: {indicator}")
    return "未找到匹配公式，请重新输入指标名称。", graph.to_state()


async def _execute_query(user_id: str, slots: dict, graph: ContextGraph):
    """
    🚀 执行公式查询与结果格式化，并更新 graph + history。
    """
    indicator = slots.get("indicator")
    formula = slots.get("formula")
    time_str = slots.get("timeString")
    time_type = slots.get("timeType")

    logger.info(f"⚙️ 调用 platform_api.query_platform(formula={formula}, time={time_str}, type={time_type})")

    try:
        if inspect.iscoroutinefunction(platform_api.query_platform):
            result = await platform_api.query_platform(formula, time_str, time_type)
        else:
            result = await asyncio.to_thread(platform_api.query_platform, formula, time_str, time_type)
        logger.info(f"✅ 平台查询成功: {result}")
    except Exception as e:
        logger.exception("❌ platform_api 查询失败: %s", e)
        return f"执行查询时出错: {e}", graph.to_state()

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

    # 🧱 更新图谱
    graph.add_node(indicator, time_str, time_type)
    graph_store[user_id] = graph

    # 🧾 写入历史
    state = await get_state(user_id)
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
    await update_state(user_id, state)

    logger.info("📘 已更新历史记录与图谱。")
    return reply, graph.to_state()
