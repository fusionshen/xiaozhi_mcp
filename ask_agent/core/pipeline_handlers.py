# core/pipeline_handlers.py
import json
import asyncio
import logging
import inspect
import re
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
    if intent_info == {}:
        graph.clear_main_intent()
    set_graph(user_id, graph)
    return reply, human_reply, graph.to_state()

async def _resolve_formula(current, graph: ContextGraph):
    # 仅仅用formula 已确定，不能判断，因为如果因为网络问题导致最后一步平台接口失败，重新询问一遍会导致指标名称被覆盖，这个时候必须再查一遍
    if current["status"] == "completed":
        return None, None
    
    # ==== 0) 优先检查用户偏好 ====
    pref = graph.get_preference(current.get("indicator"))
    if pref:
        current["formula"] = pref["FORMULAID"]
        current["indicator"] = pref["FORMULANAME"]
        current["slot_status"]["formula"] = "filled"
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
        logger.info(f"🧠 自动选择高分候选公式: {top["FORMULANAME"]} (score={top['score']}) (用户输入:{current["indicator"]})")
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

# ----------------------
# 修改 _load_or_init_indicator，增加 allow_append 参数
# ----------------------
def _load_or_init_indicator(intent_info, graph: ContextGraph, allow_append: bool = True) -> dict:
    """
    与原实现类似，但允许 caller 指示是否将新创建的 active indicator append 到 intent_info["indicators"]。
    如果 allow_append=False，则返回临时 current（不修改 intent_info）。
    """
    indicators = intent_info.setdefault("indicators", [])
    # 找 active（优先返回未填 formula 的 active）
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
        if allow_append:
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
        return f"查询失败: {e}", reply_templates.reply_api_error(), False 

    val = None
    if isinstance(result, dict):
        val = result.get("value") or next(iter(result.values()), None)
    elif isinstance(result, list) and result:
        val = result
        
    indicator_entry["value"] = val
    reply = reply_templates.simple_reply(indicator_entry)
    indicator_entry["note"] = reply
    human_reply = reply_templates.reply_success_single(indicator_entry)
    return reply, human_reply, True

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
    machine_reply = "\n".join(item.get("note", "").strip() for item in entries_results if item.get("note")) or "没有成功的查询结果。"
    logger.info(f"📊 slot_fill 汇总结果: {machine_reply}")
    # 成功查询后重置 intent（保持习惯）
    return _finish(user_id, graph, user_input, {}, machine_reply, reply_templates.reply_success_list(entries_results))

# ==== 2. 判断是否为重选场景 ====
def _is_reselect_intent(intent_info: dict, current_intent: dict | None, user_input: str) -> bool:
    """
    判断是否为“重选”场景：
    - intent_list 最后两项均为 clarify（连续两次 clarify）
    - 且 current_intent 含 candidates（来自轻量解析/LLM）
    - 或者用户输入包含“重选”/“重新选择”/包含数字但不是单纯数字选择（如 '重选 2'）
    """
    il = intent_info.get("intent_list", [])
    if len(il) >= 2 and il[-2:] == ["clarify", "clarify"]:
        return True
    # 另外判断 user_input 本身（比如 "重选 2" / "重新选第2项"）
    if re.search(r"重选|重新|再选|换个|选第|选", user_input):
        return True
    # 若 current_intent 明确带 candidates，也视为可能重选
    if current_intent and current_intent.get("candidates"):
        return True
    return False

# ------------------------- clarify 选择备选项 -------------------------
async def handle_clarify(
        user_id: str, 
        user_input: str, 
        graph: ContextGraph,
        current_intent: dict | None = None
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
    # ==== 2. 判断是否为重选场景 ====
    is_reselect = _is_reselect_intent(intent_info, current_intent, user_input)
    # ==== 3. 加载 indicator（若是重选，不直接 append 新 active） ====
    # 如果是重选，我们不希望 _load_or_init_indicator 把 "重选 2" 等临时 active 写入 intent_info.indicators
    current = _load_or_init_indicator(intent_info, graph, allow_append=not is_reselect)
    # ==== 3. 如果是数字，则尝试选择候选公式，如果使用大模型判断，假如在有备选列表情况下，用户完整输入某个指标名称，user_input不是数字，也会是clarify ====
    reply, human_reply, done = _handle_formula_choice(current, user_input, graph)
    if not done:
        # 说明还需要用户继续选择
        return _finish(user_id, graph, user_input, intent_info, reply, human_reply)
    # ==== 4. 若公式未确定，调用 _resolve_formula ====
    if current["slot_status"]["formula"] != "filled":
        reply, human_reply = await _resolve_formula(current, graph)
        if reply:
            # “请选择…” 或 “未找到公式” 之类的提示
            return _finish(user_id, graph, user_input, intent_info, reply, human_reply)

    # ==== 5. 若时间未填写 ====
    if current["slot_status"]["time"] != "filled":
        reply = f"好的，要查【{current['indicator']}】，请告诉我时间。"
        human_reply = reply_templates.reply_ask_time(current['indicator'])
        current["note"] = reply
        return _finish(user_id, graph, user_input, intent_info, reply, human_reply)
    
    # ==== 6. 公式 + 时间都有，执行查询 ====
    reply, human_reply, done = await _execute_query(current)
    if not done:
        return _finish(user_id, graph, user_input, intent_info, reply, human_reply)
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
    return _finish(user_id, graph, user_input, {}, reply, human_reply)

def _handle_formula_choice(
    current: dict,
    user_input: str,
    graph: ContextGraph,
    is_reselect: bool = False,
    current_intent: dict | None = None
):
    """
    返回 (reply, human_reply, done)
    - done=True  表示公式选择完成
    - done=False 表示需要继续 clarify

    【核心逻辑变化】
    -------------------------------------------
    clarify 重选时：
    1. 找到 current["indicator"] 对应旧的 preference（用 FORMULANAME 匹配）
    2. 根据 current_intent["candidates"][0] 找到用户真正选中的候选项
    3. 更新 preference
    4. 更新 current（不更新 node）
    -------------------------------------------
    """

    cands = current.get("formula_candidates") or []
    if not cands:
        return (
            "上下文中没有可选公式，请重新输入指标。",
            reply_templates.reply_no_formula_in_context(),
            False
        )

    # =======================================
    # clarify 重选逻辑（用户输入的是编号）
    # =======================================
    if is_reselect and user_input.isdigit():
        number = int(user_input)

        # ---- 1. 找到编号相同的候选项 ----
        matched = None
        for item in cands:
            if int(item.get("number")) == number:
                matched = item
                break

        if not matched:
            return (
                f"未找到编号为 {user_input} 的公式，请重新输入正确编号。",
                reply_templates.reply_invalid_formula_index(len(cands)),
                False
            )

        # ---- 2. 找到旧 preference：FORMULANAME == current.indicator ----
        old_key = None
        old_prefs = graph.meta.get("preferences", {})

        for key, pref in old_prefs.items():
            if pref.get("FORMULANAME") == current["indicator"]:
                old_key = key
                break

        # 如果找不到，说明用户从未对这个公式产生偏好，也无所谓
        if old_key:
            graph.meta["preferences"][old_key] = {
                "FORMULAID": matched["FORMULAID"],
                "FORMULANAME": matched["FORMULANAME"],
            }
            logger.info(f"🔄 clarify 重选偏好更新：{old_key} => {matched['FORMULANAME']}")

        # ---- 3. 更新 current（不更新 node）----
        current["formula"] = matched["FORMULAID"]
        current["indicator"] = matched["FORMULANAME"]
        current["slot_status"]["formula"] = "filled"

        return None, None, True

    # =======================================
    # 以下为第一次 clarify 的普通逻辑
    # =======================================

    # --- 数字编号选择 ---
    if user_input.isdigit():
        # 数字选择：匹配 candidate["number"] == user_input
        matched = None
        for item in cands:
            # 支持 "1" == 1 的情况
            if str(item.get("number")) == user_input:
                matched = item
                break

        if not matched:
            return (
                f"未找到编号为 {user_input} 的指标，请输入已有编号。",
                reply_templates.reply_invalid_formula_index(len(cands)),
                False
            )

        # 添加偏好（首次输入 key = current.indicator）
        graph.add_preference(current["indicator"], matched["FORMULAID"], matched["FORMULANAME"])

        current["formula"] = matched["FORMULAID"]
        current["indicator"] = matched["FORMULANAME"]
        current["slot_status"]["formula"] = "filled"
        return None, None, True

    # --- 名称精确匹配 ---
    exact_matches = [
        item for item in cands
        if item["FORMULANAME"].lower() == user_input.lower()
    ]
    if len(exact_matches) == 1:
        chosen = exact_matches[0]
        graph.add_preference(current["indicator"], chosen["FORMULAID"], chosen["FORMULANAME"])

        current["formula"] = chosen["FORMULAID"]
        current["indicator"] = chosen["FORMULANAME"]
        current["slot_status"]["formula"] = "filled"
        return None, None, True

    # --- 模糊匹配 ---
    fuzzy_matches = [
        item for item in cands
        if user_input.lower() in item["FORMULANAME"].lower()
    ]
    if len(fuzzy_matches) == 1:
        chosen = fuzzy_matches[0]
        graph.add_preference(current["indicator"], chosen["FORMULAID"], chosen["FORMULANAME"])

        current["formula"] = chosen["FORMULAID"]
        current["indicator"] = chosen["FORMULANAME"]
        current["slot_status"]["formula"] = "filled"
        return None, None, True

    if len(fuzzy_matches) > 1:
        reply = (
            f"找到多个公式名称包含「{user_input}」，请通过编号选择：\n" +
            "\n".join(f"{i['number']}. {i['FORMULANAME']}" for i in fuzzy_matches)
        )
        return reply, reply_templates.reply_formula_name_ambiguous(user_input, fuzzy_matches), False

    # --- 无匹配，替换 indicator ---
    current["indicator"] = user_input
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
        reply, human_reply = await _resolve_formula(entry, graph)
        if reply:
            # 需要用户选择公式
            return _finish(user_id, graph, user_input, intent_info, reply, human_reply)
        
        # 3.3 补齐时间
        if entry["slot_status"]["time"] != "filled":
            # 从 last node 恢复
            last = graph.get_last_completed_node()
            if last and last.get("indicator_entry", {}).get("indicator"):
                last_entry = last["indicator_entry"]
                logger.info("🧩 从最近节点恢复 indicator 时间: %s", last_entry.get("indicator"))
                entry["timeString"] = last_entry.get("timeString")
                entry["timeType"] = last_entry.get("timeType")
                entry["slot_status"]["time"] = "filled"
            else:
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

# ------------------------- 对比、偏差 -------------------------
async def handle_compare(
        user_id: str, 
        user_input: str, 
        graph: ContextGraph, 
        current_intent: dict | None = None
):
    """
    compare 主入口（重构版）
    - 支持 one-step / two-step / three-step
    - 复用 _load_or_init_indicator, _resolve_formula, _execute_query, _finish
    - 所有分支通过 _finish 统一写状态并返回 (reply, human_reply, state)
    - 最终输出为：表格（reply_success_list） + LLM 分析总结
    """
    logger.info("🔀 [compare] enter | user=%s, input=%s", user_id, user_input)
    user_input = str(user_input or "").strip()

    # ensure intent_info
    intent_info = graph.ensure_intent_info() or {}
    intent_info.setdefault("user_input_list", []).append(user_input)
    intent_info.setdefault("intent_list", []).append("compare")
    graph.set_main_intent("compare")
    indicators = intent_info.setdefault("indicators", [])

    # Acquire candidates from current_intent if present
    candidates = []
    if current_intent and isinstance(current_intent, dict):
        candidates = current_intent.get("candidates") or []

    # ------------------------- 辅助局部函数 -------------------------
    async def _record_and_finish_after_compare(sid, tid, left_entry, right_entry):
        """
        记录 relation、清理 intent、写 history，并返回统一格式（reply, human_reply, state）
        reply: 机器文本简短提示
        human_reply: 人性化 Markdown（表格 + LLM 分析）
        """
        # call LLM comparator (pass the two indicator_entry objects)
        analysis = await call_compare_llm(left_entry, right_entry)
        # record relation
        graph.add_relation("compare", source_id=sid, target_id=tid,
                           meta={"via": "pipeline.compare", "user_input": intent_info.get("user_input_list"), "result": analysis})
        return _finish(user_id, graph, user_input, {}, analysis, reply_templates.compare_summary(left_entry, right_entry))

    async def _one_step_flow():
        """
        candidates >= 2: parse前两个candidate，保证公式/time，查询（或取历史node），然后 LLM 对比
        """
        logger.info("🔎 compare: one-step 使用 candidates 解析: %s", candidates)
        parsed_items = []
        # only consider first two candidates
        for c in candidates[:2]:
            item = default_indicators()
            try:
                parsed = await parse_user_input(c)
                for key in ("indicator", "formula", "timeString", "timeType"):
                    if parsed.get(key):
                        item[key] = parsed[key]
            except Exception as e:
                logger.warning("parse_user_input 单 candidate 解析失败: %s -> %s", c, e)
            item["slot_status"]["time"] = "filled" if item.get("timeString") and item.get("timeType") else "missing"
            parsed_items.append(item)

        # if user gave more than 2, warn them
        if len(candidates) > 2:
            reply = "当前只支持两项对比，请提供两个要对比的指标，或改问趋势/分析。"
            return _finish(user_id, graph, user_input, intent_info, reply, reply_templates.reply_compare_too_many_candidates())

        # replace intent indicators
        intent_info["indicators"] = parsed_items

        node_pairs = []  # tuples of (node_id, indicator_entry, platform_result)
        for item in parsed_items:
            if not item.get("indicator"):
                return _finish(user_id, graph, user_input, intent_info, "请告诉我您要对比的指标名称。", reply_templates.reply_ask_indicator())

            # resolve formula (uses your existing helper that returns (reply, human_reply) when needs user)
            formula_reply, human_reply = await _resolve_formula(item, graph)
            if formula_reply:
                # persist intent_info and ask user to choose formula / re-enter
                return _finish(user_id, graph, user_input, intent_info, formula_reply, human_reply)

            # ensure time
            if item.get("slot_status", {}).get("time") != "filled":
                ask = f"好的，要对比【{item.get('indicator')}】，请告诉我时间。"
                item["note"] = ask
                return _finish(user_id, graph, user_input, intent_info, ask, reply_templates.reply_compare_single_missing_time(item.get("indicator")))

            # try retrieve existing node
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

            # execute platform query
            reply, human_reply, done = await _execute_query(item)
            if not done:
                return _finish(user_id, graph, user_input, intent_info, reply, human_reply)
            item["status"] = "completed"
             # 必须在addNode前
            graph.set_intent_info(intent_info)
            # 写入 graph.node
            node_id = graph.add_node(item)
            node_obj = graph.get_node(node_id)
            node_pairs.append((node_id, node_obj.get("indicator_entry")))

        # must have two entries
        if len(node_pairs) != 2:
            return _finish(user_id, graph, user_input, intent_info, "对比失败，未能获得两条有效数据。", reply_templates.reply_compare_no_data())

        left_entry = node_pairs[0][1]
        right_entry = node_pairs[1][1]

        sid = node_pairs[0][0]
        tid = node_pairs[1][0]
        return await _record_and_finish_after_compare(sid, tid, left_entry, right_entry)
    
    async def _two_step_flow():
        """
        candidates == 1:
          - 找到 base completed indicator（优先 intent_info，再 graph）
          - 复制 base -> current，parse single candidate 覆盖字段（indicator/time/...）
          - resolve formula/time -> 若缺槽则提示
          - 查询或读取历史 node -> 得到两条数据 -> LLM compare -> record
        """
        logger.info("🔎 compare: two-step (single candidate)")

        # find base completed indicator
        base_indicator = None
        # prefer from intent_info indicators
        for ind in reversed(indicators):
            if ind.get("status") == "completed":
                base_indicator = ind
                break
        # fallback to graph nodes
        if not base_indicator and graph.nodes:
            base_indicator = graph.nodes[-1].get("indicator_entry")

        if not base_indicator:
            reply = "无可用的参考指标，请先进行至少一次查询以便进行对比。"
            return _finish(user_id, graph, user_input, intent_info, reply, reply_templates.reply_compare_no_left_data())

        # get or create active current indicator (copy base)
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
                "slot_status": {"formula": "missing", "time": "missing"},
                "value": None,
                "note": None,
                "formula_candidates": base_indicator.get("formula_candidates"),
            }
            indicators.append(current_indicator)

        # parse the single candidate to overwrite fields
        try:
            parsed = await parse_user_input(candidates[0])
            for key in ("indicator", "formula", "timeString", "timeType"):
                if parsed.get(key):
                    current_indicator[key] = parsed[key]
        except Exception as e:
            logger.warning("parse_user_input 单 candidate 解析失败: %s -> %s", candidates[0], e)

        # special handling: shorthand "计划" -> replace base_indicator wording
        def _convert_to_plan_name(last_indicator: str, new_partial_indicator: str):
            if not new_partial_indicator:
                return new_partial_indicator
            if new_partial_indicator in ("计划", "计划值", "计划报出值"):
                mapping = {"实绩": "计划", "实绩值": "计划值", "实绩报出值": "计划报出值"}
                for k, v in mapping.items():
                    if k in (last_indicator or ""):
                        return (last_indicator or "").replace(k, v)
            return new_partial_indicator

        current_indicator["indicator"] = _convert_to_plan_name(base_indicator.get("indicator"), current_indicator.get("indicator"))
        current_indicator["slot_status"]["time"] = "filled" if current_indicator.get("timeString") and current_indicator.get("timeType") else "missing"

        if not current_indicator.get("indicator"):
            return _finish(user_id, graph, user_input, intent_info, "请告诉我您要对比的指标名称。", reply_templates.reply_ask_indicator())

        # resolve formula
        formula_reply, human_reply = await _resolve_formula(current_indicator, graph)
        if formula_reply:
            return _finish(user_id, graph, user_input, intent_info, formula_reply, human_reply)

        # ensure time
        if current_indicator.get("slot_status", {}).get("time") != "filled":
            current_indicator["note"] = f"好的，要对比【{current_indicator.get('indicator')}】，请告诉我时间。"
            return _finish(user_id, graph, user_input, intent_info, current_indicator["note"], reply_templates.reply_compare_single_missing_time(current_indicator.get("indicator")))

        # try find a matching node
        nid = graph.find_node(current_indicator.get("indicator"), current_indicator.get("timeString"))
        if nid:
            node_obj = graph.get_node(nid)
            ie = node_obj.get("indicator_entry", {})
            current_indicator["value"] = ie.get("value")
            current_indicator["note"] = ie.get("note")
            current_indicator["status"] = "completed"

            # base node id (prefer actual node if exists)
            base_node_id = graph.find_node(base_indicator.get("indicator"), base_indicator.get("timeString"))
            base_node_obj = graph.get_node(base_node_id) if base_node_id else {"indicator_entry": base_indicator}

            sid = base_node_id
            tid = nid
            return await _record_and_finish_after_compare(sid, tid, base_node_obj, ie)
        else:
            # execute query
            reply, human_reply, done = await _execute_query(current_indicator)
            if not done:
                return _finish(user_id, graph, user_input, intent_info, reply, human_reply)
            current_indicator["status"] = "completed"
            # 必须在addNode前
            graph.set_intent_info(intent_info)
            # 写入 graph.node
            nid_new = graph.add_node(current_indicator)
            new_node = graph.get_node(nid_new)

            base_node_id = graph.find_node(base_indicator.get("indicator"), base_indicator.get("timeString"))
            base_node_obj = graph.get_node(base_node_id) if base_node_id else {"indicator_entry": base_indicator}

            return await _record_and_finish_after_compare(base_node_id, nid_new, base_node_obj, new_node)

    async def _three_step_flow():
        """
        candidates == 0: use last two nodes from graph
        """
        logger.info("🔎 compare: three-step (no candidates) - 回溯 graph 最近两节点")
        if len(graph.nodes) >= 2:
            node1 = graph.nodes[-2]
            node2 = graph.nodes[-1]
            ie1 = node1.get("indicator_entry", {})
            ie2 = node2.get("indicator_entry", {})

            sid = node1.get("id")
            tid = node2.get("id")
            return await _record_and_finish_after_compare(sid, tid, ie1, ie2)

        # not enough history
        reply = "当前没有足够的历史查询结果用于对比，请先进行查询以生成两条数据。"
        return _finish(user_id, graph, user_input, intent_info, reply, reply_templates.reply_compare_no_data())

    # ------------------------- 分支路由 -------------------------
    try:
        if len(candidates) >= 2:
            return await _one_step_flow()
        elif len(candidates) == 1:
            return await _two_step_flow()
        else:
            return await _three_step_flow()
    except Exception as e:
        logger.exception("❌ handle_compare 内部错误: %s", e)
        # 保证统一出口
        err_reply = f"对比处理发生错误: {e}"
        return _finish(user_id, graph, user_input, intent_info, err_reply, reply_templates.reply_api_error())

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

    from core.llm_energy_intent_parser import EnergyIntentParser
    parser = EnergyIntentParser()
    user_input = "本月1、2号高炉工序能耗是多少"
    current_info = await parser.parse_intent(user_input)
    print(current_info)

    # 测试批量查询
    _, reply, graph_state = await handle_list_query(user_id, user_input, graph, current_info)
    print("Single Query Reply 1:", reply)
    print(json.dumps(graph_state, indent=2, ensure_ascii=False))

    # 测试输入备选
    _, reply, graph_state = await handle_single_query(user_id, "高炉工序能耗本月计划是多少", graph)
    print("Single Query Reply 3:", reply)
    print(json.dumps(graph_state, indent=2, ensure_ascii=False))

    # 测试一步对比
    # reply, _, graph_state = await handle_compare(user_id, user_input, graph, current_info)
    # print("Single Query Reply:", reply)
    # print(json.dumps(graph_state, indent=2, ensure_ascii=False))

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
