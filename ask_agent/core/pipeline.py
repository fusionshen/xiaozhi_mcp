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
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

# 显示候选数量（和 main_v1 中保持一致）
TOP_N = 5

# 内存缓存：每个用户的上下文图谱（session -> ContextGraph）
graph_store = {}


async def process_message(user_id: str, message: str, state: dict):
    """
    用户消息处理管线（融合 V1 单指标单时间逻辑 + V2 上下文框架）：
      步骤：
        1) 加载 slots 状态与上下文图谱（graph）
        2) 若存在 formula_candidates 且用户输入为数字 => 选择公式并继续
        3) 否则调用 llm_energy_indicator_parser.parse_user_input 补全 slots
        4) 若缺失 indicator/time => 引导用户补全
        5) 通过 formula_api 查找公式：支持精确匹配、自动选择高分候选、或返回候选列表
        6) 若信息齐全则调用 platform_api 查询并格式化结果
        7) 查询成功后把“完整查询记录”写入 ContextGraph 并清空 slots
    返回:
      (reply_str, graph_state_dict)
    """
    user_input = (message or "").strip()
    logger.info(f"🟢 [process_message] user={user_id!r} input={user_input!r}")

    # 1️⃣ 加载/恢复 graph 与 slots
    graph = graph_store.setdefault(user_id, ContextGraph.from_state(state))
    session_state = await get_state(user_id)
    # 确保 slots 存在并有默认结构
    session_state.setdefault("slots", {
        "indicator": None,
        "formula": None,
        "formula_candidates": None,
        "awaiting_confirmation": False,
        "timeString": None,
        "timeType": None
    })
    slots = session_state["slots"]

    logger.info(f"当前 slots (before parsing): {slots}")

    # 2️⃣ 若当前存在候选公式且输入为数字 => 用户在选择候选
    if slots.get("formula_candidates") and user_input.isdigit():
        idx = int(user_input.strip()) - 1
        candidates = slots["formula_candidates"]
        logger.info("检测到用户在选择候选公式（digit input）。index=%s, candidates_count=%d", idx, len(candidates))

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

    # 3️⃣ 若存在候选但输入不是数字 => 清空候选并继续解析（与 V1 行为一致）
    if slots.get("formula_candidates"):
        logger.info("🧩 非数字输入且存在候选，清空候选并重新解析输入。")
        slots["formula_candidates"] = None
        slots["formula"] = None
        await update_state(user_id, session_state)

    # 4️⃣ 调用 LLM 解析以补全 indicator/time（重用旧解析器）
    try:
        parsed = await parse_user_input(user_input)
        logger.info("🔍 LLM 解析结果: %s", parsed)
    except Exception as e:
        logger.exception("❌ parse_user_input 调用失败: %s", e)
        parsed = {"indicator": None, "timeString": None, "timeType": None}

    # 合并 slots（仅补全缺失信息，不覆盖已有）
    for k in ("indicator", "timeString", "timeType"):
        if parsed.get(k):
            logger.debug("补全 slots: %s -> %s", k, parsed.get(k))
            slots[k] = parsed.get(k)
    await update_state(user_id, session_state)
    logger.info("当前 slots (after parsing): %s", slots)

    # 5️⃣ 如果 indicator 缺失，询问用户提供指标
    if not slots.get("indicator"):
        logger.info("⚠️ indicator 缺失，要求用户补全指标名称。")
        return "请告诉我您要查询的指标名称。", graph.to_state()

    # 6️⃣ 使用 formula_api 查找公式（可能会返回精确匹配或候选列表）
    logger.info("🔎 调用 formula_api.formula_query_dict 查询公式, indicator=%s", slots["indicator"])
    try:
        formula_resp = await asyncio.to_thread(formula_api.formula_query_dict, slots["indicator"])
    except Exception as e:
        logger.exception("❌ 调用 formula_api 失败: %s", e)
        return f"查找公式时出错: {e}", graph.to_state()

    logger.info("formula_api 返回摘要: done=%s, exact_matches=%s, candidates_len=%s",
                formula_resp.get("done"), bool(formula_resp.get("exact_matches")), len(formula_resp.get("candidates", [])))

    # 7️⃣ 处理 formula_api 结果
    if formula_resp.get("done") and formula_resp.get("exact_matches"):
        match = formula_resp["exact_matches"][0]
        slots["formula"] = match["FORMULAID"]
        slots["indicator"] = match["FORMULANAME"]
        await update_state(user_id, session_state)
        logger.info("✅ 精确匹配公式: %s (FORMULAID=%s)", slots["indicator"], slots["formula"])

        # 如果没有时间，询问时间
        if not (slots.get("timeString") and slots.get("timeType")):
            return f"好的，要查【{slots['indicator']}】，请告诉我时间。", graph.to_state()

        # 完整 -> 执行查询
        return await _execute_query(user_id, slots, graph)

    else:
        # 有候选但没有精确匹配
        candidates = formula_resp.get("candidates", []) or []
        if candidates:
            logger.info("🔢 找到 %d 个候选公式（按 score 排序）", len(candidates))
            # 高分候选自动选择（与 V1 逻辑一致）
            top = candidates[0]
            logger.info("最高候选: %s (score=%s)", top.get("FORMULANAME"), top.get("score"))
            if top.get("score", 0) > 100:
                chosen = top
                slots["formula"] = chosen["FORMULAID"]
                slots["indicator"] = chosen["FORMULANAME"]
                slots["formula_candidates"] = None
                await update_state(user_id, session_state)
                logger.info("🧠 自动选择高分候选公式: %s (score=%s)", chosen.get("FORMULANAME"), chosen.get("score"))

                # 若时间缺失，询问时间
                if not (slots.get("timeString") and slots.get("timeType")):
                    return f"好的，要查【{slots['indicator']}】，请告诉我时间。", graph.to_state()

                # 否则执行查询
                return await _execute_query(user_id, slots, graph)

            # 否则展示候选并等待用户选择
            slots["formula_candidates"] = candidates[:TOP_N]
            await update_state(user_id, session_state)
            msg_lines = ["请从以下候选公式选择编号："]
            for c in candidates[:TOP_N]:
                # 保证 number 字段存在，若无则用索引 +1
                number = c.get("number") or (c.get("FORMULAID") or "N/A")
                msg_lines.append(f"{number}) {c['FORMULANAME']} (score {c.get('score', 0):.2f})")
            logger.info("➡️ 返回候选列表供用户选择（count=%d）", len(slots["formula_candidates"]))
            return "\n".join(msg_lines), graph.to_state()
        else:
            logger.info("❌ 未找到匹配公式: indicator=%s", slots["indicator"])
            return "未找到匹配公式，请重新输入指标名称。", graph.to_state()


async def _execute_query(user_id: str, slots: dict, graph: ContextGraph):
    """
    执行单指标单时间查询，成功后更新 ContextGraph 并清理 slots。
    自动判断 platform_api.query_platform 是同步函数还是协程。
    """
    try:
        formula = slots.get("formula")
        indicator = slots.get("indicator")
        time_str = slots.get("timeString")
        time_type = slots.get("timeType")

        logger.info("🚀 执行平台查询: indicator=%s, formula=%s, time=%s, timeType=%s",
                    indicator, formula, time_str, time_type)

        # ✅ 自动判断同步/异步
        if inspect.iscoroutinefunction(platform_api.query_platform):
            result = await platform_api.query_platform(formula, time_str, time_type)
        else:
            result = await asyncio.to_thread(platform_api.query_platform, formula, time_str, time_type)

        logger.info("✅ platform_api 返回: %s", result)

        # ---- 格式化结果 ----
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

        # ✅ 记录 ContextGraph
        graph.add_node(indicator, time_str, time_type)
        graph_store[user_id] = graph
        logger.info("🔗 已把完整查询写入 ContextGraph：indicators=%s times=%s", graph.indicators, graph.times)

        # ✅ 清空 slots
        state = await get_state(user_id)
        state["slots"] = _default_slots()
        await update_state(user_id, state)
        logger.info("🧹 已清空用户 slots，等待下次查询")

        return reply, graph.to_state()

    except Exception as e:
        logger.exception("❌ 执行查询时出错: %s", e)
        return f"查询时出错: {e}", graph.to_state()



def _default_slots():
    """重置默认 slots（与 main_v1 保持一致）"""
    return {
        "indicator": None,
        "formula": None,
        "formula_candidates": None,
        "awaiting_confirmation": False,
        "timeString": None,
        "timeType": None
    }
