# core/pipeline_handlers.py
import json
import asyncio
import logging
import inspect
from core.context_graph import ContextGraph, default_indicators
from core.llm_energy_indicator_parser import parse_user_input
from tools import formula_api, platform_api
from core.pipeline_context import set_graph, get_graph
from core.llm_indicator_compare import call_compare_llm
from core import reply_templates


logger = logging.getLogger("pipeline.handlers")
if not logger.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )

TOP_N = 5

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
        parsed = await parse_user_input(user_input)
        for key in ("indicator", "formula", "timeString", "timeType"):
            if parsed.get(key):
                current[key] = parsed[key]
    except Exception as e:
        logger.warning("⚠️ LLM 解析失败: %s", e)
    
    # 尝试从暂存中获取时间
    if not parsed.get("timeString"):
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
    formula_reply, human_reply = await _resolve_formula(current)
    if formula_reply:                                         # 用户需要手动选择
        return _finish(user_id, graph, user_input, intent_info, formula_reply, human_reply)
    # ----------------------------
    # step 4 : 若公式 & 时间齐全 → 执行平台查询
    # ----------------------------
    if current["slot_status"]["formula"] == "filled" and current["slot_status"]["time"] == "filled":
        val, result = await _execute_query(current)
        reply = reply_templates.simple_reply(current, result)
        current["value"] = val
        current["note"] = reply
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
        # 正常结束
        human_reply = reply_templates.reply_success_single(current, result)
        return _finish(user_id, graph, user_input, {}, reply, human_reply)
    # ----------------------------
    # step 4.2 ：缺时间，继续询问
    # ----------------------------
    ask = f"好的，要查【{current['indicator']}】，请告诉我时间。"
    current["note"] = ask
    return _finish(user_id, graph, user_input, intent_info, ask, reply_templates.reply_ask_time(current['indicator']))

# ------------------------- 辅助函数 -------------------------
def _finish(user_id: str,graph: ContextGraph, user_input, intent_info, reply, human_reply: str = None):
    graph.add_history(user_input, reply)
    graph.set_intent_info(intent_info)
    set_graph(user_id, graph)
    return reply, human_reply, graph.to_state()

async def _resolve_formula(current):
    # formula 已确定
    if current["slot_status"]["formula"] == "filled":
        return None, None

    resp = await asyncio.to_thread(formula_api.formula_query_dict, current["indicator"])
    exact = resp.get("exact_matches") or []
    cand = resp.get("candidates") or []

    # 精确匹配
    if exact:
        chosen = exact[0]
        current["formula"] = chosen["FORMULAID"]
        current["indicator"] = chosen["FORMULANAME"]
        current["slot_status"]["formula"] = "filled"
        return None, None

    # 高分候选（score > 100）
    if cand and cand[0].get("score", 0) > 100:
        top = cand[0]
        current["formula"] = top["FORMULAID"]
        current["indicator"] = top["FORMULANAME"]
        current["slot_status"]["formula"] = "filled"
        return None, None

    # 有候选但需要用户选择
    if cand:
        current["formula_candidates"] = cand[:TOP_N]
        current["slot_status"]["formula"] = "missing"
        lines = [
            f"没有完全匹配的【{current['indicator']}】，请选择编号（或重新输入更精确的名称）："
        ]
        for i, c in enumerate(cand[:TOP_N], 1):
            lines.append(f"{i}) {c['FORMULANAME']} (score {c.get('score',0):.2f})")
        return "\n".join(lines), reply_templates.reply_candidates(current['indicator'], current["formula_candidates"])

    # 完全无候选
    current["slot_status"]["formula"] = "missing"
    return f"未找到匹配公式，请重新输入指标。", reply_templates.reply_no_formula()

def _load_or_init_indicator(intent_info, graph: ContextGraph):
    indicators = intent_info.setdefault("indicators", [])
    # 找 active
    active = next((i for i in indicators if i.get("status") == "active"), None)
    if active:
        return active

    # 从 last node 恢复
    last = graph.get_last_completed_node()
    if last and last.get("indicator_entry", {}).get("indicator"):
        entry = last["indicator_entry"]
        logger.info("🧩 从最近节点恢复 indicator: %s", entry.get("indicator"))
        new_one = {
            "status": "active",
            "indicator": entry.get("indicator"),
            "formula": entry.get("formula"),
            "timeString": entry.get("timeString"),
            "timeType": entry.get("timeType"),
            "slot_status": {"formula": "missing", "time": "missing"},
            "value": None,
            "note": None,
            "formula_candidates": entry.get("formula_candidates"),
        }
        indicators.append(new_one)
        return new_one
    # 创建默认 indicator
    logger.info("⚠️ 无历史节点可用，创建默认 indicator。")
    new_default = default_indicators()
    indicators.append(new_default)
    return new_default

async def _execute_query(indicator_entry):
    formula = indicator_entry.get("formula")
    time_str = indicator_entry.get("timeString")
    time_type = indicator_entry.get("timeType")

    try:
        if inspect.iscoroutinefunction(platform_api.query_platform):
            result = await platform_api.query_platform(formula, time_str, time_type)
        else:
            result = await asyncio.to_thread(platform_api.query_platform, formula, time_str, time_type)
        logger.info(f"⚙️ 平台查询成功: {result}")
    except Exception as e:
        logger.exception("❌ platform_api 查询失败: %s", e)
        return None, f"查询失败: {e}", reply_templates.reply_api_error()

    val = None
    if isinstance(result, dict):
        val = result.get("value") or next(iter(result.values()), None)
    elif isinstance(result, list) and result:
        val = result[0].get("itemValue") or result[0].get("value") or result[0].get("v")

    return val, result

# ------------------------- Slot 填充 基本属于时间-------------------------
async def handle_slot_fill(
    user_id: str,
    user_input: str,
    graph: ContextGraph,
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

        parsed = await parse_user_input(candidates[0])
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
        formula_reply, human_reply_formula = await _resolve_formula(ind)
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
            val, result = await _execute_query(ind)
            raw_reply = reply_templates.simple_reply(ind, result)
            ind["value"] = val
            ind["note"] = raw_reply
            ind["status"] = "completed"
            graph.add_node(ind)
            entries_results.append({
                "indicator_entry": ind,
                "result": result  # 注意：这里保留 full human reply 结构
            })
        else:
            ind["note"] = f"❗ 指标【{ind.get('indicator')}】缺少时间信息"
            entries_results.append({
                "indicator_entry": ind,
                "result": reply_templates.reply_ask_time(ind.get("indicator"))  
            })
    # ----------------------------
    # step 4: 意图跳转 compare / list_query
    # ----------------------------
    main_intent = graph.get_main_intent() or None
    if "compare" == main_intent:
        logger.info("🔄 solt_fill 完成并检测到 compare 上下文，继续执行 handle_compare...")
        return await handle_compare(
            user_id, 
            f"{user_input} -> system:完成 solt_fill 并检测到 compare 上下文，继续执行 handle_compare...", 
            graph
        )
    
    if "list_query" == main_intent:
        logger.info("🔄 solt_fill 完成并检测到 list_query 上下文，继续执行 handle_list_query...")
        return await handle_list_query(
            user_id, 
            f"{user_input} -> system:完成 solt_fill 并检测到 list_query 上下文，继续执行 handle_list_query...", 
            graph
        )
    # ----------------------------
    # step 5: 正常结束
    # ----------------------------
    # 必须在清空意图前更新图谱
    graph.set_intent_info(intent_info)
    set_graph(user_id, graph)
    machine_reply = "\n".join(item.get("indicator_entry", {}).get("note", "").strip() for item in entries_results if item.get("indicator_entry", {}).get("note")) or "没有成功的查询结果。"
    logger.info(f"📊 slot_fill 汇总结果: {machine_reply}")
    # 成功查询后重置 intent（保持习惯）
    return _finish(user_id, graph, user_input, {}, machine_reply, reply_templates.reply_success_list(entries_results))

# ------------------------- clarify 选择备选项 -------------------------
async def handle_clarify(
        user_id: str, 
        user_input: str, 
        graph: ContextGraph
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
    # ==== 2. 加载 indicator（优先 active；无则恢复；再无则 default） ====
    current = _load_or_init_indicator(intent_info, graph)

    # ==== 3. 如果是数字，则尝试选择候选公式 ====
    if user_input.isdigit():
        reply, human_reply, done = _handle_formula_choice(current, user_input)
        if not done:
            # 说明还需要用户继续选择
            return _finish(user_id, graph, user_input, intent_info, reply, human_reply)
    # ==== 4. 若公式未确定，调用 _resolve_formula ====
    if current["slot_status"]["formula"] != "filled":
        sys_reply, human_reply = await _resolve_formula(current)
        if sys_reply:
            # “请选择…” 或 “未找到公式” 之类的提示
            return _finish(user_id, graph, user_input, intent_info, sys_reply, human_reply)

    # ==== 5. 若时间未填写 ====
    if current["slot_status"]["time"] != "filled":
        reply = f"好的，要查【{current['indicator']}】，请告诉我时间。"
        human_reply = reply_templates.reply_ask_time(current['indicator'])
        current["note"] = reply
        return _finish(user_id, graph, user_input, intent_info, reply, human_reply)
    
    # ==== 6. 公式 + 时间都有，执行查询 ====
    val, result = await _execute_query(current)
    # 写入结果
    current["value"] = val
    reply = reply_templates.simple_reply(current, result)
    current["note"] = reply
    current["status"] = "completed"
    # 保存 intent_info
    graph.set_intent_info(intent_info)
    # 写入 node
    graph.add_node(current)
    # ==== 7. 判断 compare / list_query 是否继续 ====
    main_intent = graph.get_main_intent() or None
    if "compare" == main_intent:
        logger.info("🔄 clarify 完成并检测到 compare 上下文，继续执行 handle_compare...")
        # 连续判断需要找到当前intent中active的indicator，作为当前current_info传入即可
        current_intents = [
            ind.get("indicator")
            for ind in intent_info.get("indicators")
            if ind.get("status") == "active" and ind.get("indicator")
        ]
        print(f"current_intents:{current_intents}")
        return await handle_compare(user_id, f"{user_input} -> system:完成 clarify 并检测到 compare 上下文，继续执行 handle_compare...", graph, current_intent={"candidates": current_intents})

    if "list_query" == main_intent:
        logger.info("🔄 clarify 完成并检测到 list_query 上下文，继续执行 handle_list_query...")
        return await handle_list_query(user_id, f"{user_input} -> system:完成 clarify 并检测到 list_query 上下文，继续执行 handle_list_query...", graph)
        
    # ==== 8. 单查询完成，重置 intent ====
    human_reply = reply_templates.reply_success_single(current, result)
    return _finish(user_id, graph, user_input, {}, reply, human_reply)

def _handle_formula_choice(current, user_input: str):
    """
    返回 (reply, done)
    done=True 表示已经选择完成，可以继续下一步
    done=False 表示还需用户继续选择
    """
    if not user_input.isdigit():
        return None, None, True

    idx = int(user_input) - 1
    cands = current.get("formula_candidates") or []

    if not cands:
        return "上下文中没有可选公式，请重新输入指标。", reply_templates.reply_no_formula_in_context(), False

    if not (0 <= idx < len(cands)):
        return f"请输入编号 1~{len(cands)} 选择公式。", reply_templates.reply_invalid_formula_index(len(cands)), False

    chosen = cands[idx]
    current["formula"] = chosen["FORMULAID"]
    current["indicator"] = chosen["FORMULANAME"]
    current["slot_status"]["formula"] = "filled"
    return None, None, True

# ------------------------- 批量查询 -------------------------
async def handle_list_query(
        user_id: str, 
        user_input: str, 
        graph: ContextGraph, 
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
            entry = default_indicators()
            entry["status"] = "active"

            try:
                parsed_res = await parse_user_input(c)
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
        
        # 3.2 解析公式
        reply, human_reply = await _resolve_formula(entry)
        if reply:
            # 需要用户选择公式
            return _finish(user_id, graph, user_input, intent_info, reply, human_reply)
        
                # 3.3 补齐时间
        if entry["slot_status"]["time"] != "filled":
            reply = f"要查【{entry['indicator']}】，请告诉我时间。"
            human_reply = reply_templates.reply_ask_time(entry["indicator"])
            return _finish(user_id, graph, user_input, intent_info, reply, human_reply)

        # 3.4 查询缓存节点
        nid = graph.find_node(entry["indicator"], entry["timeString"])
        if nid:
            node = graph.get_node(nid)
            ie = node.get("indicator_entry", {})
            entry["value"] = ie.get("value")
            entry["note"] = ie.get("note")
            entry["status"] = "completed"

            entries_results.append({
                "indicator_entry": entry,
                "result": ie.get("value")  # 这里简化：你也可以保留原结构
            })
            continue

        # 3.5 平台查询
        val, result = await _execute_query(entry)
        entry["value"] = val
        entry["note"] = reply_templates.simple_reply(entry, result)
        entry["status"] = "completed"

        graph.set_intent_info(intent_info)
        graph.add_node(entry)

        entries_results.append({
            "indicator_entry": entry,
            "result": result  # 注意：这里保留 full human reply 结构
        })
    # -------------------------------------------------------
    # ④ 所有指标完成 → 写关系、输出回复
    # -------------------------------------------------------
    logger.info("🟦 所有指标已完成 batch 查询 (%s 个)", len(entries_results))

    # 1) 从每个 entry 取 note（保证非 None 并去除两端空白）
    # 2) 拼接成一个最终字符串（每个指标之间用两个换行或分隔线更易读）
    machine_reply = "\n".join(item.get("indicator_entry", {}).get("note", "").strip() for item in entries_results if item.get("indicator_entry", {}).get("note")) or "没有成功的查询结果。"

    # 写 group 关系
    sids = [graph.find_node(item["indicator_entry"]["indicator"],
                             item["indicator_entry"]["timeString"]) 
             for item in entries_results ]
    
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
    return _finish(user_id, graph, user_input, intent_info, machine_reply, reply_templates.reply_success_list(entries_results))

# ------------------------- 对比、偏差 -------------------------
async def handle_compare(user_id: str, user_input: str, graph: ContextGraph, current_intent: dict | None = None):
    """
    Compare 统一处理逻辑（一步/两步/三步模式）：

    一步：用户当前输入解析出 >=2 条 candidates
            → 全部解析补全 slot → 查询 → 得到两条 entry.note → LLM 比较

    两步：用户当前输入解析出 ==1 条 candidate
            → 从 graph 取最后一条已完成 entry
            → 复制其 indicator 数据
            → 用 candidate 的解析结果替换（可替换指标/时间/计划 vs 实绩）
            → 查询新 entry → 与旧 entry 比较

    三步：用户当前输入解析出 0 条 candidate
            → 直接从 graph.nodes 回溯最近两个已成功节点
            → 不再查平台数据 → 直接 LLM 比较

    所有步骤:
      - 若过程中缺公式 or 时间 → intent_info.pending 标记 → 返回提示用户补槽
      - 结果写回 graph.nodes 与 intent_info.compare_history
    """
    user_input = str(user_input or "").strip()
    logger.info("🔀 进入 handle_compare，user=%s, input=%s", user_id, user_input)

    # Ensure we have a working intent_info (use snapshot recovery)
    intent_info = graph.ensure_intent_info() or {}
    intent_info.setdefault("user_input_list", []).append(user_input)
    intent_info.setdefault("intent_list", []).append("compare")
    graph.set_main_intent("compare")
    indicators = intent_info.setdefault("indicators", [])

    # Acquire candidates from current_intent if present
    candidates = []
    if current_intent and isinstance(current_intent, dict):
        candidates = current_intent.get("candidates") or []

    # If intent_info already has indicators (e.g. from previous steps), we operate on that list.
    # We'll append/modify indicators list as needed per scenario.

    # ---------- One-step (>=2 candidates supplied) ----------
    if len(candidates) >= 2:
        logger.info("🔎 compare: 使用 candidates 解析: %s", candidates)
        parsed_indicators = []
        for c in candidates:
            # parse each candidate into a default indicator entry
            n = default_indicators()
            try:
                parsed = await parse_user_input(c)
                for key in ("indicator", "formula", "timeString", "timeType"):
                    if parsed.get(key):
                        n[key] = parsed[key]
            except Exception as e:
                logger.warning("parse_user_input 单 candidate 解析失败: %s -> %s", candidates[0], e)
            n["slot_status"]["time"] = "filled" if n.get("timeString") and n.get("timeType") else "missing"
            parsed_indicators.append(n)

        # If more than 2 provided, refuse (per your rule)
        if len(parsed_indicators) > 2:
            reply = "当前只支持两项对比，请只提供两个要对比的目标，或改问趋势/分析。"
            graph.add_history(user_input, reply)
            graph.set_intent_info(intent_info)
            set_graph(user_id, graph)
            logger.warning("⚠️ compare: 用户提供超过两项 candidates")
            return reply, graph.to_state()
        
        # replace intent indicators
        intent_info["indicators"] = parsed_indicators
        indicators = intent_info["indicators"]
        # ensure both items have nodes/values
        node_pairs = []
        for item in indicators:
            # ---------- 缺指标 ----------
            if not item.get("indicator"):
                reply = "请告诉我您要对比的指标名称。"
                graph.add_history(user_input, reply)
                graph.set_intent_info(intent_info)
                set_graph(user_id, graph)
                return reply, graph.to_state()

            # ---------- 查询公式 ----------
            if not item["slot_status"]["formula"] == "filled":
                formula_resp = await asyncio.to_thread(formula_api.formula_query_dict, item["indicator"])
                exact_matches = formula_resp.get("exact_matches") or []
                candidates = formula_resp.get("candidates") or []
                if exact_matches:
                    chosen = exact_matches[0]
                    item["formula"] = chosen["FORMULAID"]
                    item["indicator"] = chosen["FORMULANAME"]
                    item["slot_status"]["formula"] = "filled"
                    item["note"] = "精确匹配公式"
                elif candidates and candidates[0].get("score", 0) > 100:
                    top = candidates[0]
                    item["formula"] = top["FORMULAID"]
                    item["indicator"] = top["FORMULANAME"]
                    item["slot_status"]["formula"] = "filled"
                    item["note"] = f"高分候选公式 (score {top.get('score')})"
                elif candidates:
                    item["formula_candidates"] = candidates[:TOP_N]
                    item["slot_status"]["formula"] = "missing"
                    lines = [f"没有完全匹配的【{item["indicator"]}】指标，请从以下候选选择编号(或者重新输入尽量精确的指标名称："]
                    for i, c in enumerate(candidates[:TOP_N], 1):
                        lines.append(f"{i}) {c['FORMULANAME']} (score {c.get('score',0):.2f})")
                    reply = "\n".join(lines) 
                    graph.add_history(user_input, reply)
                    graph.set_intent_info(intent_info)
                    set_graph(user_id, graph)
                    return reply, graph.to_state()
                else:
                    item["slot_status"]["formula"] = "missing"
                    item["note"] = "未找到匹配公式"
                    reply = f"未找到匹配公式，请重新输入指标名称。" 
                    graph.add_history(user_input, reply)
                    graph.set_intent_info(intent_info)
                    set_graph(user_id, graph)
                    return reply, graph.to_state()
            #  check time 
            if  not item["slot_status"]["time"] == "filled":
                reply = f"好的，要查【{item['indicator']}】，请告诉我时间。"
                graph.add_history(user_input, reply)
                item["note"] = reply
                graph.set_intent_info(intent_info)
                set_graph(user_id, graph)
                return reply, graph.to_state()
                
            # Try find existing node identical
            nid = graph.find_node(item.get("indicator"), item.get("timeString"))
            if nid:
                node = graph.get_node(nid)
                ie = node.get("indicator_entry")
                item["value"] = ie.get("value")
                item["note"] = ie.get("note")
                item["status"] = "completed"
                graph.set_intent_info(intent_info)
                node_pairs.append((nid, ie))
                continue
            # else query platform
            if item["slot_status"]["formula"] == "filled" and item["slot_status"]["time"] == "filled":
                val, result = await _execute_query(item)
                item["value"] = val
                item["note"] = reply_templates.simple_reply(item, result)
                item["status"] = "completed"
                # 必须在addNode前
                graph.set_intent_info(intent_info)
                # 写入 graph.node
                node_id = graph.add_node(item)
                other_node = graph.get_node(node_id)
                node_pairs.append((node_id, other_node.get("indicator_entry")))

        # now have two node entries
        left = node_pairs[0][1]
        right = node_pairs[1][1]

        # call LLM with two notes
        analysis = await call_compare_llm(left, right)

        # write relation and history
        sid = node_pairs[0][0]
        tid = node_pairs[1][0]
        graph.add_relation("compare", source_id=sid, target_id=tid, meta={"via": "pipeline.compare", "user_input": intent_info.get("user_input_list"), "result": analysis})
        # 成功查询重置意图
        graph.set_intent_info({})
        graph.clear_main_intent()
        graph.add_history(user_input, analysis)
        set_graph(user_id, graph)
        logger.info("✅ compare(one-step) 完成")
        return analysis, graph.to_state()

    # ---------- Two-step (1 candidate): take last completed indicator as base, then parse candidate to replace fields ----------
    if len(candidates) == 1:
        logger.info("🔎 compare: single candidate 情形 -> two-step flow")
        # find last completed indicator in intent_info or graph
        base_indicator = None
        # prefer from intent_info indicators
        for ind in reversed(indicators):
            if ind.get("status") == "completed":
                base_indicator = ind
                break
        # fallback to graph nodes
        if not base_indicator and graph.nodes:
            base_indicator = graph.nodes[-1]["indicator_entry"]

        if not base_indicator:
            reply = "⚠️ 无可用的参考指标，请先进行至少一次查询以便进行对比。"
            graph.add_history(user_input, reply)
            graph.set_intent_info(intent_info)
            set_graph(user_id, graph)
            logger.warning("⚠️ compare(two-step) 无 base_indicator")
            return reply, graph.to_state()

        # parse the single candidate (it was placed in 'candidates' earlier; here we assume exactly 1)
        current_indicator = None
        for ind in reversed(indicators):
            if ind.get("status") == "active":
                current_indicator = ind
                break
        if not current_indicator:
            current_indicator = {
                "status": "active",
                "indicator": base_indicator.get("indicator"),
                "formula": base_indicator.get("formula"),
                "timeString": base_indicator.get("timeString"),
                "timeType": base_indicator.get("timeType"),
                "slot_status": {
                    "formula": "missing",
                    "time": "missing"
                },
                "value": None,
                "note": None,
                "formula_candidates": base_indicator.get("formula_candidates"),
            }
            indicators.append(current_indicator)
        # if candidate is a time only or indicator only, parse and overwrite corresponding fields
        try:
            parsed = await parse_user_input(candidates[0])
            for key in ("indicator", "formula", "timeString", "timeType"):
                if parsed.get(key):
                    current_indicator[key] = parsed[key]
        except Exception as e:
            logger.warning("parse_user_input 单 candidate 解析失败: %s -> %s", candidates[0], e)

        # 计划特例
        def convert_to_plan_name(last_indicator: str, new_partial_indicator: str) -> str:
            if new_partial_indicator in ["计划", "计划值", "计划报出值"]:
                # 常见“实绩/计划”关键词【你可以扩展】
                mapping = {
                    "实绩": "计划",
                    "实绩值": "计划值",
                    "实绩报出值": "计划报出值",
                }
                for k, v in mapping.items():
                    if k in last_indicator:
                        return last_indicator.replace(k, v)   
            return new_partial_indicator

        current_indicator["indicator"] = convert_to_plan_name(base_indicator.get("indicator"), current_indicator["indicator"])

        current_indicator["slot_status"]["time"] = "filled" if current_indicator.get("timeString") and current_indicator.get("timeType") else "missing"
            
        # ---------- 缺指标 ----------
        if not current_indicator.get("indicator"):
            reply = "请告诉我您要对比的指标名称。"
            graph.add_history(user_input, reply)
            graph.set_intent_info(intent_info)
            set_graph(user_id, graph)
            return reply, graph.to_state()

        # ---------- 查询公式 ----------
        if not current_indicator["slot_status"]["formula"] == "filled":
            print(current_indicator["indicator"])
            formula_resp = await asyncio.to_thread(formula_api.formula_query_dict, current_indicator["indicator"])
            print(formula_resp)
            exact_matches = formula_resp.get("exact_matches") or []
            candidates = formula_resp.get("candidates") or []

            if exact_matches:
                chosen = exact_matches[0]
                current_indicator["formula"] = chosen["FORMULAID"]
                current_indicator["indicator"] = chosen["FORMULANAME"]
                current_indicator["slot_status"]["formula"] = "filled"
                current_indicator["note"] = "精确匹配公式"
            elif candidates and candidates[0].get("score", 0) > 100:
                top = candidates[0]
                current_indicator["formula"] = top["FORMULAID"]
                current_indicator["indicator"] = top["FORMULANAME"]
                current_indicator["slot_status"]["formula"] = "filled"
                current_indicator["note"] = f"高分候选公式 (score {top.get('score')})"
            elif candidates:
                current_indicator["formula_candidates"] = candidates[:TOP_N]
                current_indicator["slot_status"]["formula"] = "missing"
                lines = [f"没有完全匹配的【{current_indicator["indicator"]}】指标，请从以下候选选择编号(或者重新输入尽量精确的指标名称："]
                for i, c in enumerate(candidates[:TOP_N], 1):
                    lines.append(f"{i}) {c['FORMULANAME']} (score {c.get('score',0):.2f})")
                reply = "\n".join(lines) 
                graph.add_history(user_input, reply)
                graph.set_intent_info(intent_info)
                set_graph(user_id, graph)
                return reply, graph.to_state()
            else:
                current_indicator["slot_status"]["formula"] = "missing"
                current_indicator["note"] = "未找到匹配公式"
                reply = f"未找到匹配公式，请重新输入指标名称。" 
                graph.add_history(user_input, reply)
                graph.set_intent_info(intent_info)
                set_graph(user_id, graph)
                return reply, graph.to_state()

        # Now ensure both base (possibly modified copy) and the other recent node have values
        # Prepare the other existing node (the one to compare against): prefer previous completed node different from base copy
        other_node = None
        for node in reversed(graph.nodes):
            ie = node.get("indicator_entry", {})
            # only indicator and timeString is ok
            if ie.get("indicator") == current_indicator.get("indicator") and ie.get("timeString") == current_indicator.get("timeString"):
                other_node = node
                break
            
        if not other_node:
            # ---------- 执行查询 ----------
            if current_indicator["slot_status"]["formula"] == "filled" and current_indicator["slot_status"]["time"] == "filled":
                val, result = await _execute_query(current_indicator)
                current_indicator["value"] = val
                current_indicator["note"] = reply_templates.simple_reply(current_indicator, result)
                current_indicator["status"] = "completed"
                # 必须在addNode前
                graph.set_intent_info(intent_info)
                # 写入 graph.node
                node_id = graph.add_node(current_indicator)
                other_node = graph.get_node(node_id)

        # Now produce two notes and call LLM

        analysis = await call_compare_llm(base_indicator, current_indicator)
        
        sid = graph.find_node(base_indicator.get("indicator"), base_indicator.get("timeString"))
        # write relation and history
        graph.add_relation("compare", source_id=sid, target_id=other_node.get("id"), meta={"via": "pipeline.compare", "user_input": intent_info.get("user_input_list"), "result": analysis})
        # 成功查询重置意图
        graph.set_intent_info({})
        graph.clear_main_intent()
        graph.add_history(user_input, analysis)
        set_graph(user_id, graph)
        logger.info("✅ compare(two-step) 完成")
        return analysis, graph.to_state()
    
    # ---------- Three-step (no candidates): use last two nodes from graph ----------
    logger.info("🔎 compare: 未提供 candidates，尝试从 graph 回溯最近两个节点")
    recent = graph.nodes[-2:] if len(graph.nodes) >= 2 else []
    if recent and len(recent) >= 2:
        node1 = recent[-2]
        node2 = recent[-1]
        ie1 = node1.get("indicator_entry", {})
        ie2 = node2.get("indicator_entry", {})

        analysis = await call_compare_llm(ie1, ie2)

        # write relation
        sid = node1.get("id")
        tid = node2.get("id")
        graph.add_relation("compare", source_id=sid, target_id=tid, meta={"via": "pipeline.compare", "user_input": intent_info.get("user_input_list"), "result": analysis})
        # 成功查询重置意图
        graph.set_intent_info({})
        graph.clear_main_intent()
        graph.add_history(user_input, analysis)
        set_graph(user_id, graph)
        logger.info("✅ compare(three-step) 完成")
        return analysis, graph.to_state()

# ------------------------- 趋势分析 -------------------------
async def handle_analysis(user_id: str, message: str, graph: ContextGraph):
    logger.info("📈 进入 analysis 模式（趋势扩展查询）")
    return "趋势查询功能正在开发中。", graph.to_state()



# ------------------------- 测试 main -------------------------
async def main():
    from tools import formula_api
    # 只初始化一次，不会重复加载
    formula_api.initialize()

    user_id = "test_user"
    graph = get_graph(user_id) or ContextGraph()
    set_graph(user_id, graph)

    # 测试单指标查询
    reply, _, graph_state = await handle_single_query(user_id, "2022年上半年高炉工序能耗是多少", graph)
    print("Single Query Reply:", reply)
    print(json.dumps(graph_state, indent=2, ensure_ascii=False))

    # # 测试选择备选
    # reply, graph_state = await handle_clarify(user_id, 1, graph)
    # print("Single Query Reply 2:", reply)
    # print(json.dumps(graph_state, indent=2, ensure_ascii=False))

    # # # 测试补齐时间
    # reply, graph_state = await handle_slot_fill(user_id, "今天", graph, {"candidates": ["今天"]})
    # print("Single Query Reply 3:", reply)
    # print(json.dumps(graph_state, indent=2, ensure_ascii=False))

    # # 测试问另外的时间
    # reply, graph_state = await handle_slot_fill(user_id, "哪昨天呢？", graph, {"candidates": ["昨天"]})
    # print("Single Query Reply 4:", reply)
    # print(json.dumps(graph_state, indent=2, ensure_ascii=False))
    
    # 再查询一个指标（可测试对比）
    # msg2 = "昨天高炉工序能耗是多少"
    # reply2, graph_state2 = await handle_single_query(user_id, msg2, graph)
    # print("Single Query Reply 2:", reply2)
    # print(json.dumps(graph_state2, indent=2, ensure_ascii=False))

    # # 对比
    # cmp_reply, _ = await handle_compare(user_id, "对比最新两条数据", graph)
    # print("Compare Reply:", cmp_reply)


if __name__ == "__main__":
    asyncio.run(main())
