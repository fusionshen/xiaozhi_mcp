# core/pipeline_handlers.py
import asyncio
import logging
import inspect
from core.context_graph import ContextGraph
from core.llm_energy_indicator_parser import parse_user_input
from tools import formula_api, platform_api
from core.llm_client import safe_llm_chat
from agent_state import get_state, update_state, default_slots
from core.pipeline_context import set_graph  # ✅ 新增

logger = logging.getLogger("pipeline.handlers")
if not logger.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )

TOP_N = 5

async def handle_new_query(user_id: str, message: str, graph: ContextGraph):
    """
    基础能源查询（默认意图）：
    - 调用公式查询接口
    - 执行平台数据查询
    - 更新图谱与历史
    """
    session_state = await get_state(user_id)
    session_state.setdefault("slots", default_slots())
    slots = session_state["slots"]
    logger.info(f"当前 slots (before parsing): {slots}")
    
    user_input = str(message or "").strip()
    # ---------- 数字输入选择公式 ----------
    if slots.get("formula_candidates") and user_input.isdigit():
        idx = int(user_input) - 1
        candidates = slots["formula_candidates"]
        logger.info(f"🔢 检测到候选选择 index={idx}, count={len(candidates)}")
        if 0 <= idx < len(candidates):
            chosen = candidates[idx]
            slots.update({
                "formula": chosen["FORMULAID"],
                "indicator": chosen["FORMULANAME"],
                "formula_candidates": None,
                "awaiting_confirmation": False
            })
            await update_state(user_id, session_state)
            logger.info(f"✅ 用户选择公式: {slots['indicator']} (FORMULAID={slots['formula']})")
            
            # 如果缺时间，提示补全
            if not (slots.get("timeString") and slots.get("timeType")):
                slots["awaiting_confirmation"] = True
                await _update_slots(user_id, slots)
                return f"好的，要查【{slots['indicator']}】，请告诉我时间。", graph.to_state()

            # 否则执行查询
            slots["awaiting_confirmation"] = False
            await _update_slots(user_id, slots)    
            return await _execute_query(user_id, message, graph)
        logger.warning("⚠️ 用户输入的候选编号超范围: %s", user_input)
        slots["awaiting_confirmation"] = True
        await _update_slots(user_id, slots)
        return f"请输入编号 1~{len(candidates)} 选择公式。", graph.to_state()

    # ---------- 非数字输入重新解析 ----------
    if slots.get("formula_candidates"):
        slots["formula_candidates"] = None
        slots["formula"] = None
        await update_state(user_id, session_state)
        logger.info("🧹 已清空 formula_candidates，准备重新解析")

    # ---------- 调用 LLM 解析补全 ----------
    try:
        parsed = await parse_user_input(user_input)
        for key in ("indicator", "timeString", "timeType"):
            if parsed.get(key):
                slots[key] = parsed[key]
                logger.debug(f"🧩 补全 slots: {key}={parsed[key]}")
    except Exception as e:
        logger.exception("❌ parse_user_input 失败: %s", e)
        parsed = {}

    await update_state(user_id, session_state)
    logger.info(f"📦 当前 slots (after parsing): {slots}")

    # 5️⃣ 如果指标缺失，要求用户补全
    if not slots.get("indicator"):
        logger.info("⚠️ 缺少 indicator，提示用户补全。")
        slots["awaiting_confirmation"] = True
        await _update_slots(user_id, slots)
        return "请告诉我您要查询的指标名称。", graph.to_state()

    # 6️⃣ 使用 formula_api 查找公式
    try:
        logger.info(f"🔎 调用 formula_api 查询公式: {slots["indicator"]}")
        formula_resp = await asyncio.to_thread(formula_api.formula_query_dict, slots["indicator"])
    except Exception as e:
        logger.exception("❌ 调用 formula_api 失败: %s", e)
        slots["awaiting_confirmation"] = True
        await _update_slots(user_id, slots)
        return f"查找公式时出错: {e}", graph.to_state()

    exact_matches = formula_resp.get("exact_matches") or []
    candidates = formula_resp.get("candidates") or []
    logger.info(f"📊 formula_api 返回: exact={len(exact_matches)}, candidates={len(candidates)}")

    # 精确匹配
    if exact_matches:
        chosen = exact_matches[0]
        slots["formula"] = chosen["FORMULAID"]
        slots["indicator"] = chosen["FORMULANAME"]
        slots["formula_candidates"] = None
        await _update_slots(user_id, slots)
        logger.info(f"✅ 精确匹配公式: {slots['indicator']} (FORMULAID={slots['formula']})")
        
        # 如果没有时间，询问时间
        if not (slots.get("timeString") and slots.get("timeType")):
            slots["awaiting_confirmation"] = True
            await _update_slots(user_id, slots)
            return f"好的，要查【{slots['indicator']}】，请告诉我时间。", graph.to_state()

        slots["awaiting_confirmation"] = False
        await _update_slots(user_id, slots)
        return await _execute_query(user_id, slots, graph)

    # 候选匹配
    if candidates:
        top = candidates[0]
        logger.info("🔢 找到 %d 个候选公式, 最高候选: %s (score=%s)", len(candidates), top.get("FORMULANAME"), top.get("score"))
        if top.get("score", 0) > 100:
            slots["formula"] = top["FORMULAID"]
            slots["indicator"] = top["FORMULANAME"]
            slots["formula_candidates"] = None
            await _update_slots(user_id, slots)
            logger.info(f"🧠 自动选择高分候选公式: {slots['indicator']} (score={top['score']})")

            if not (slots.get("timeString") and slots.get("timeType")):
                slots["awaiting_confirmation"] = True
                await _update_slots(user_id, slots)
                return f"好的，要查【{slots['indicator']}】，请告诉我时间。", graph.to_state()
            
            # 否则执行查询
            slots["awaiting_confirmation"] = False
            await _update_slots(user_id, slots)   
            return await _execute_query(user_id, slots, graph)
        else:
            slots["formula_candidates"] = candidates[:TOP_N]
            slots["awaiting_confirmation"] = True
            await _update_slots(user_id, slots)
            msg_lines = ["请从以下候选公式选择编号："]
            for i, c in enumerate(candidates[:TOP_N], 1):
                msg_lines.append(f"{i}) {c['FORMULANAME']} (score {c.get('score', 0):.2f})")
            logger.info("➡️ 返回候选公式供用户选择")
            return "\n".join(msg_lines), graph.to_state()

    # --- Step 4. 无匹配 ---
    logger.info(f"❌ 未找到匹配公式: {indicator}")
    slots["awaiting_confirmation"] = True
    await _update_slots(user_id, slots)
    return f"未找到匹配公式，请重新输入指标名称。", graph.to_state()


async def _execute_query(user_id: str, slots: dict, graph: ContextGraph):
    """执行平台查询并更新图谱与历史"""
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

    # --- 格式化结果 ---
    reply = _format_query_result(result, indicator, time_str, time_type)

    # --- 更新状态 ---
    state = await get_state(user_id)
    state.setdefault("history", [])
    history = state["history"]

    last_indicator = next((h["indicator"] for h in reversed(history) if h.get("indicator")), None)
    if last_indicator and last_indicator != indicator:
        try:
            graph.update_node(old_indicator=last_indicator, new_indicator=indicator)
        except Exception:
            graph.add_node(indicator, time_str, time_type)
    else:
        graph.add_node(indicator, time_str, time_type)

    history.append({
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


def _format_query_result(result, indicator, time_str, time_type):
    if isinstance(result, dict):
        val = result.get("value") or next(iter(result.values()), None)
        unit = result.get("unit", "")
        return f"✅ {indicator} 在 {time_str} ({time_type}) 的值是 {val} {unit}"
    elif isinstance(result, list):
        lines = [f"{r.get('clock') or r.get('time') or r.get("timestamp")}: {r.get('itemValue') or r.get('value') or r.get("v")}" for r in result]
        return f"✅ {indicator} 在 {time_str} ({time_type}) 的查询结果:\n" + "\n".join(lines)
    else:
        return f"✅ {indicator} 在 {time_str} ({time_type}) 的查询结果: {result}"


async def _update_slots(user_id, slots):
    """更新会话状态"""
    state = await get_state(user_id)
    state["slots"].update(slots)
    await update_state(user_id, state)

async def handle_compare(user_id: str, message: str, graph: ContextGraph):
    state = await get_state(user_id)
    state.setdefault("history", [])
    history = state["history"]
    state.setdefault("slots", default_slots())
    slots = state["slots"]

    indicator = slots.get("indicator")
    formula = slots.get("formula")
    time_str = slots.get("timeString")
    time_type = slots.get("timeType")

    do_compare = slots.get("intent") == "compare" or any(
        r.get("source") and r.get("target") for r in graph.get_relations("compare")
    )

    if do_compare:
        resolved = None
        for r in reversed(graph.get_relations("compare")):
            if r.get("source") and r.get("target"):
                resolved = (r.get("source"), r.get("target"))
                break
        if not resolved:
            resolved = graph.resolve_compare_nodes()

        if not resolved:
            if len(history) >= 2:
                src_rec, tgt_rec = history[-2], history[-1]
                src_id = graph.find_node(src_rec.get("indicator"), src_rec.get("timeString")) or graph.add_node(src_rec.get("indicator"), src_rec.get("timeString"), src_rec.get("timeType"))
                tgt_id = graph.find_node(tgt_rec.get("indicator"), tgt_rec.get("timeString")) or graph.add_node(tgt_rec.get("indicator"), tgt_rec.get("timeString"), tgt_rec.get("timeType"))
                graph.add_relation("compare", source_id=src_id, target_id=tgt_id)
                resolved = (src_id, tgt_id)
            else:
                set_graph(user_id, graph)  # ✅ 替代 graph_store[user_id] = graph
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
                return reply, graph.to_state()

        src_id, tgt_id = resolved
        src_node, tgt_node = graph.get_node(src_id), graph.get_node(tgt_id)

        def _find_history_for(node):
            for rec in reversed(history):
                if rec.get("indicator") == node.get("indicator") and rec.get("timeString") == node.get("timeString"):
                    return rec
            return None

        src_rec = _find_history_for(src_node)
        tgt_rec = _find_history_for(tgt_node)

        if not src_rec or not src_rec.get("result"):
            q_src = f"{src_node.get('indicator')} 在 {src_node.get('timeString')} 的值是多少"
            await handle_new_query(user_id, q_src, graph.to_state())
            state = await get_state(user_id)
            history = state.get("history", [])
            src_rec = _find_history_for(src_node)

        if not tgt_rec or not tgt_rec.get("result"):
            q_tgt = f"{tgt_node.get('indicator')} 在 {tgt_node.get('timeString')} 的值是多少"
            await handle_new_query(user_id, q_tgt, graph.to_state())
            state = await get_state(user_id)
            history = state.get("history", [])
            tgt_rec = _find_history_for(tgt_node)

        val_a = src_rec.get("result")
        val_b = tgt_rec.get("result")

        analysis = ""
        if val_a is not None and val_b is not None:
            llm_prompt = f"""
你是能源分析助手。请基于下面两次查询结果给出简洁对比（一句话总结 + 差值与百分比）：
- 指标: {src_node.get('indicator')}
- 时间A: {src_node.get('timeString')}, 结果A: {val_a}
- 时间B: {tgt_node.get('timeString')}, 结果B: {val_b}
"""
            analysis = await safe_llm_chat(llm_prompt)
        else:
            analysis = "\n⚠️ 无法找到可用于对比的数值结果。"

        graph.add_relation("compare", source_id=src_id, target_id=tgt_id, meta={"via": "pipeline.compare", "user_input": message,"result": analysis})
        set_graph(user_id, graph)  # ✅ 替代 graph_store[user_id] = graph

        return analysis, graph.to_state()


async def handle_expand(user_id: str, message: str, graph: ContextGraph):
    logger.info("📈 进入 expand 模式（趋势扩展查询）")
    return "趋势查询功能正在开发中。", graph.to_state()


async def handle_same_indicator_new_time(user_id: str, message: str, graph: ContextGraph):
    logger.info("🔁 进入 same_indicator_new_time 模式。")
    return await handle_new_query(user_id, message, graph)


async def handle_list_query(user_id: str, message: str, graph: ContextGraph):
    logger.info("📋 进入 list_query 模式（批量指标查询）。")
    return "批量查询功能正在开发中。", graph.to_state()
