# core/pipeline.py

import asyncio
import logging
import inspect
from core.context_graph import ContextGraph
from core.llm_energy_indicator_parser import parse_user_input
from tools import formula_api, platform_api
from agent_state import get_state, update_state
from core.llm_client import safe_llm_chat

logger = logging.getLogger("pipeline")
if not logger.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )

TOP_N = 5

# 内存缓存：每个用户的上下文图谱（session -> ContextGraph）
graph_store = {}

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

async def process_message(user_id: str, message: str, graph_state_dict: dict):
    """
    用户消息处理管线：
      - 补全 slots（indicator/time）
      - 查找公式（formula_api）
      - 执行查询（platform_api）
      - 更新 graph & history
      - 支持 compare 自动补查与分析
    返回: (reply_str, graph_state_dict)
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

    # 3️⃣ 非数字输入且存在候选 => 清空候选重新解析
    if slots.get("formula_candidates"):
        logger.info("🧩 清空旧候选，重新进入解析流程。")
        slots["formula_candidates"] = None
        slots["formula"] = None
        await update_state(user_id, session_state)

    # 4️⃣ 调用 LLM 解析补全 indicator/time
    try:
        parsed = await parse_user_input(user_input)
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

    # 6️⃣ 使用 formula_api 查找公式
    try:
        logger.info(f"🔎 调用 formula_api 查询公式: {slots["indicator"]}")
        formula_resp = await asyncio.to_thread(formula_api.formula_query_dict, slots["indicator"])
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
    执行公式查询与结果格式化，并更新 graph + history，支持 compare 补查。
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
    reply = ""
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

    # 更新 graph & history
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

    # ---------- compare ----------
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
                graph_store[user_id] = graph
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
            await process_message(user_id, q_src, graph.to_state())
            state = await get_state(user_id)
            history = state.get("history", [])
            src_rec = _find_history_for(src_node)

        if not tgt_rec or not tgt_rec.get("result"):
            q_tgt = f"{tgt_node.get('indicator')} 在 {tgt_node.get('timeString')} 的值是多少"
            await process_message(user_id, q_tgt, graph.to_state())
            state = await get_state(user_id)
            history = state.get("history", [])
            tgt_rec = _find_history_for(tgt_node)

        def _extract_value(res_text):
            import re
            if not res_text:
                return None
            m = re.search(r"值是\s*([\-0-9\.eE]+)", res_text) or re.search(r":\s*([\-0-9\.eE]+)", res_text) or re.search(r"([\-0-9\.eE]+)", res_text)
            return m.group(1) if m else None

        val_a = float(_extract_value(src_rec.get("result"))) if src_rec else None
        val_b = float(_extract_value(tgt_rec.get("result"))) if tgt_rec else None

        analysis = ""
        if val_a is not None and val_b is not None:
            diff = val_b - val_a
            percent = (diff / val_a * 100) if val_a != 0 else None
            llm_prompt = f"""
你是能源分析助手。请基于下面两次查询结果给出简洁对比（一句话总结 + 差值与百分比）：
- 指标: {src_node.get('indicator')}
- 时间A: {src_node.get('timeString')}, 数值A: {val_a}
- 时间B: {tgt_node.get('timeString')}, 数值B: {val_b}
"""
            analysis_text = await safe_llm_chat(llm_prompt)
            analysis = f"\n\n对比分析结论：\n{analysis_text}\n（{src_node.get('timeString')}={val_a}, {tgt_node.get('timeString')}={val_b}, 差值={diff}{'' if percent is None else f', 百分比={percent:.2f}%'}）"
        else:
            analysis = "\n⚠️ 无法找到可用于对比的数值结果。"

        final_reply = reply + analysis
        graph.add_relation("compare", source_id=src_id, target_id=tgt_id, meta={"via": "pipeline.compare"})
        graph_store[user_id] = graph

        state.setdefault("history", [])
        state["history"].append({
            "user_input": slots.get("last_input", ""),
            "indicator": indicator,
            "formula": formula,
            "timeString": time_str,
            "timeType": time_type,
            "result": final_reply,
            "intent": slots.get("intent", "new_query")
        })
        await update_state(user_id, state)

        return final_reply, graph.to_state()

    # ---------- 非 compare ----------
    graph_store[user_id] = graph
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
