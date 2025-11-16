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


logger = logging.getLogger("pipeline.handlers")
if not logger.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )

TOP_N = 5

# ------------------------- 单指标查询 -------------------------
async def handle_single_query(user_id: str, user_input: str, graph: ContextGraph):
    logger.info("✅ 进入 single query 模式。")
    """
    基础能源查询：
    - 补全指标/时间
    - 调用 formula_api 查询公式
    - 自动选择公式或提示候选
    - 执行平台查询
    - 成功查询节点写入 graph.nodes，保留当时 intent_info
    """
    user_input = str(user_input or "").strip()
    logger.info(f"🔹 handle_single_query user_input={user_input}")
    # 需要提前判断，支持不选择备选，重新开始查询
    is_compare = (ri := (graph.get_intent_info() or {})) and "compare" in ri.get("intent_list", []) \
             and any(ind.get("status") == "active" for ind in ri.get("indicators", []))
    # 实际操作
    intent_info = graph.ensure_intent_info() or {}
    intent_info.setdefault("user_input_list", []).append(user_input)
    intent_info.setdefault("intent_list", []).append("single_query")  # 或 "clarify" 等

    indicators = intent_info.setdefault("indicators", [])
    
    # ---------- 查找当前 active indicator ----------
    current_indicator = None
    for ind in indicators:
        if ind.get("status") == "active":
            current_indicator = ind
            break

    # ---------- 若无 active indicator，则尝试从最近节点恢复 ----------
    if not current_indicator:
        last_node = graph.get_last_completed_node()
        if last_node:
            entry = last_node.get("indicator_entry", {})
            if entry and entry.get("indicator"):
                logger.info("🧩 从最近节点恢复 indicator: %s", entry.get("indicator"))
                current_indicator = {
                    "status": "active",
                    "indicator": entry.get("indicator"),
                    "formula": entry.get("formula"),
                    "timeString": entry.get("timeString"),
                    "timeType": entry.get("timeType"),
                    "slot_status": {
                        "formula": "missing",
                        "time": "missing"
                    },
                    "value": None,
                    "note": None,
                    "formula_candidates": entry.get("formula_candidates"),
                }
                indicators.append(current_indicator)
            else:
                logger.info("⚠️ 最近节点无有效 indicator_entry，改用默认新建。")
                current_indicator = default_indicators()
                indicators.append(current_indicator)
        else:
            logger.info("⚠️ 无历史节点可用，创建默认 indicator。")
            current_indicator = default_indicators()
            indicators.append(current_indicator)

    # ---------- LLM 补全 ----------
    try:
        parsed = await parse_user_input(user_input)
        for key in ("indicator", "formula", "timeString", "timeType"):
            if parsed.get(key):
                current_indicator[key] = parsed[key]
    except Exception as e:
        logger.warning("parse_user_input 解析候选失败: %s -> %s", user_input, e)

    current_indicator["slot_status"]["time"] = "filled" if current_indicator.get("timeString") and current_indicator.get("timeType") else "missing"

    # ---------- 缺指标 ----------
    if not current_indicator.get("indicator"):
        reply = "请告诉我您要查询的指标名称。"
        graph.add_history(user_input, reply)
        graph.set_intent_info(intent_info)
        set_graph(user_id, graph)
        return reply, graph.to_state()

    # ---------- 查询公式 ----------
    if not current_indicator["slot_status"]["formula"] == "filled":
        formula_resp = await asyncio.to_thread(formula_api.formula_query_dict, current_indicator["indicator"])
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
            lines = [f"没有完全匹配的[{current_indicator["indicator"]}]指标，请从以下候选选择编号(或者重新输入尽量精确的指标名称)："]
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

    # ---------- 执行查询 ----------
    if current_indicator["slot_status"]["formula"] == "filled" and current_indicator["slot_status"]["time"] == "filled":
        val, reply = await _execute_query(current_indicator)
        current_indicator["value"] = val
        current_indicator["note"] = reply
        current_indicator["status"] = "completed"
        # 必须在addNode前
        graph.set_intent_info(intent_info)
        # 写入 graph.node
        node_id = graph.add_node(current_indicator)

        # 连续判断需要找到当前intent中active的indicator，作为当前current_info传入即可
        if is_compare:
            logger.info("🔄 clarify 完成并检测到 compare 上下文，继续执行 handle_compare...")
            current_intents = [
                ind.get("indicator")
                for ind in intent_info.get("indicators")
                if ind.get("status") == "active" and ind.get("indicator")
            ]
            print(f"current_intents:{current_intents}")
            return await handle_compare(user_id, f"{user_input} -> system:完成 clarify 并检测到 compare 上下文，继续执行 handle_compare...", graph, current_intent={"candidates": current_intents})
        
        # 成功查询重置意图
        graph.set_intent_info({})
        graph.add_history(user_input, reply)
        set_graph(user_id, graph)
        return reply, graph.to_state()
    reply = f"好的，要查【{current_indicator['indicator']}】，请告诉我时间。"
    graph.add_history(user_input, reply)
    current_indicator["note"] = reply
    graph.set_intent_info(intent_info)
    set_graph(user_id, graph)
    return reply, graph.to_state()

# ------------------------- 辅助函数 -------------------------
async def _execute_query(indicator_entry):
    formula = indicator_entry.get("formula")
    time_str = indicator_entry.get("timeString")
    time_type = indicator_entry.get("timeType")
    indicator = indicator_entry.get("indicator")

    try:
        if inspect.iscoroutinefunction(platform_api.query_platform):
            result = await platform_api.query_platform(formula, time_str, time_type)
        else:
            result = await asyncio.to_thread(platform_api.query_platform, formula, time_str, time_type)
        logger.info(f"⚙️ 平台查询成功: {result}")
    except Exception as e:
        logger.exception("❌ platform_api 查询失败: %s", e)
        return None, f"查询失败: {e}"

    # 提取数值 和 回复
    val = None
    reply = None
    if isinstance(result, dict):
        val = result.get("value") or next(iter(result.values()), None)
        unit = result.get("unit", "")
        reply = f"✅ {indicator} 在 {time_str} ({time_type}) 的值是 {val} {unit}"
    elif isinstance(result, list) and result:
        val = result[0].get("itemValue") or result[0].get("value") or result[0].get("v")
        lines = [f"{r.get('clock') or r.get('time') or r.get("timestamp")}: {r.get('itemValue') or r.get('value') or r.get("v")}" for r in result]
        reply = f"✅ {indicator} 在 {time_str} ({time_type}) 的查询结果:\n" + "\n".join(lines)
    else:
        reply = f"✅ {indicator} 在 {time_str} ({time_type}) 的查询结果: {result}"
    return val, reply
    
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
                    lines = [f"没有完全匹配的[{item["indicator"]}]指标，请从以下候选选择编号(或者重新输入尽量精确的指标名称："]
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
                val, reply = await _execute_query(item)
                item["value"] = val
                item["note"] = reply
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
                lines = [f"没有完全匹配的[{current_indicator["indicator"]}]指标，请从以下候选选择编号(或者重新输入尽量精确的指标名称："]
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
                val, reply = await _execute_query(current_indicator)
                current_indicator["value"] = val
                current_indicator["note"] = reply
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
        graph.add_history(user_input, analysis)
        set_graph(user_id, graph)
        logger.info("✅ compare(three-step) 完成")
        return analysis, graph.to_state()

# ------------------------- 趋势分析 -------------------------
async def handle_analysis(user_id: str, message: str, graph: ContextGraph):
    logger.info("📈 进入 analysis 模式（趋势扩展查询）")
    return "趋势查询功能正在开发中。", graph.to_state()

# ------------------------- Slot 填充 基本属于时间-------------------------
async def handle_slot_fill(user_id: str, user_input: str, graph: ContextGraph, current_intent: dict | None = None):
    logger.info("🔁 进入 slot_fill 模式。")
    """
    批量时间槽位补全逻辑：
    1. 找出所有 active 的指标
    2. 解析用户输入（时间）
    3. 如果没有或多条时间 → 提示重新输入
    4. 为每个 active 指标补全时间并执行查询
    5. 汇总结果，写入 graph
    """
    user_input = str(user_input or "").strip()
    logger.info(f"🔹 handle_slot_fill user_input={user_input}")
    # 需要提前判断
    is_compare = (ri := (graph.get_intent_info() or {})) and "compare" in ri.get("intent_list", []) \
            and any(ind.get("status") == "active" for ind in ri.get("indicators", []))
    # 因为查询成功会清空当前intent_info，所以在成功查询一次后，后续问“那昨天的呢？”，会从最近的node中拉取snapshot
    intent_info = graph.ensure_intent_info() or {}
    intent_info.setdefault("user_input_list", []).append(user_input)
    intent_info.setdefault("intent_list", []).append("slot_fill") 
    indicators = intent_info.setdefault("indicators", [])

    # ---------- 找到所有 active 指标 ----------
    active_inds = [ind for ind in indicators if ind.get("status") == "active"]
    if not active_inds:
        active_inds = indicators
    
    # ---------- 解析时间 ----------
    try:
        print(current_intent)
        candidates = current_intent.get("candidates", [])
        if not candidates or len(candidates) != 1:
            reply = "抱歉，我不确定您指的时间，请重新输入（例如：去年、上月、2024年10月）。"
            graph.add_history(user_input, reply)
            graph.set_intent_info(intent_info)
            set_graph(user_id, graph)
            return reply, graph.to_state()
        parsed = await parse_user_input(candidates[0])
        logger.info(f"✅ 解析到时间候选: {parsed}")
    except Exception as e:
        reply = f"解析时间出错: {e}"
        graph.add_history(user_input, reply)
        graph.set_intent_info(intent_info)
        set_graph(user_id, graph)
        return reply, graph.to_state()

    # ---------- 批量更新 ----------
    results = []
    for ind in active_inds:
        for key in ("timeString", "timeType"):
            if parsed.get(key):
                ind[key] = parsed[key]

        ind["slot_status"]["time"] = "filled" if ind.get("timeString") and ind.get("timeType") else "missing"
                
        # ---------- 查询公式 ----------
        if not ind["slot_status"]["formula"] == "filled":
            formula_resp = await asyncio.to_thread(formula_api.formula_query_dict, ind["indicator"])
            exact_matches = formula_resp.get("exact_matches") or []
            candidates = formula_resp.get("candidates") or []

            if exact_matches:
                chosen = exact_matches[0]
                ind["formula"] = chosen["FORMULAID"]
                ind["indicator"] = chosen["FORMULANAME"]
                ind["slot_status"]["formula"] = "filled"
                ind["note"] = "精确匹配公式"
            elif candidates and candidates[0].get("score", 0) > 100:
                top = candidates[0]
                ind["formula"] = top["FORMULAID"]
                ind["indicator"] = top["FORMULANAME"]
                ind["slot_status"]["formula"] = "filled"
                ind["note"] = f"高分候选公式 (score {top.get('score')})"
            elif candidates:
                ind["formula_candidates"] = candidates[:TOP_N]
                ind["slot_status"]["formula"] = "missing"
                lines = [f"没有完全匹配的[{ind["indicator"]}]指标，请从以下候选选择编号(或者重新输入尽量精确的指标名称："]
                for i, c in enumerate(candidates[:TOP_N], 1):
                    lines.append(f"{i}) {c['FORMULANAME']} (score {c.get('score', 0):.2f})")
                reply = "\n".join(lines)
                graph.add_history(user_input, reply)
                graph.set_intent_info(intent_info)
                set_graph(user_id, graph)
                return reply, graph.to_state()
            else:
                ind["slot_status"]["formula"] = "missing"
                ind["note"] = "未找到匹配公式"
                reply = f"未找到匹配公式，请重新输入指标名称。"
                graph.add_history(user_input, reply)
                graph.set_intent_info(intent_info)
                set_graph(user_id, graph)
                return reply, graph.to_state()

        # ---------- 执行查询 ----------
        if ind["slot_status"]["formula"] == "filled":
            val, reply = await _execute_query(ind)
            ind["value"] = val
            ind["note"] = reply
            ind["status"] = "completed"
            graph.add_node(ind)
            results.append(reply)
    
    if is_compare:
            logger.info("🔄 solt_fill 完成并检测到 compare 上下文，继续执行 handle_compare...")
            return await handle_compare(user_id, f"{user_input} -> system:完成 solt_fill 并检测到 compare 上下文，继续执行 handle_compare...", graph)
    
    # ---------- 更新 graph ----------
    graph.set_intent_info(intent_info)
    set_graph(user_id, graph)
    # 成功查询重置意图
    graph.set_intent_info({})
    final_reply = "\n".join(results) if results else "没有成功的查询结果。"
    graph.add_history(user_input, final_reply)
    logger.info(f"📊 slot_fill 汇总结果: {final_reply}")
    return final_reply, graph.to_state()

# ------------------------- clarify 选择备选项 -------------------------
async def handle_clarify(user_id: str, user_input: str, graph: ContextGraph):
    logger.info("✅ 进入 clarify 模式。")
    """
    基础能源查询：
    - 选择备选
    - 调用 formula_api 查询公式
    - 自动选择公式或提示候选
    - 执行平台查询
    - 成功查询节点写入 graph.nodes，保留当时 intent_info
    """
    user_input = str(user_input or "").strip()
    logger.info(f"🔹 handle_clarify user_input={user_input}")
    # 需要提前判断
    is_compare = (ri := (graph.get_intent_info() or {})) and "compare" in ri.get("intent_list", []) \
             and any(ind.get("status") == "active" for ind in ri.get("indicators", []))
    # 实际操作
    intent_info = graph.ensure_intent_info() or {}
    intent_info.setdefault("user_input_list", []).append(user_input)
    intent_info.setdefault("intent_list", []).append("clarify")
    
    indicators = intent_info.setdefault("indicators", [])

    # ---------- 查找当前 active indicator ----------
    current_indicator = None
    for ind in indicators:
        if ind.get("status") == "active" and ind.get("formula_candidates"):
            current_indicator = ind
            break

    # 如果没有 active 的，就新建一个
    if not current_indicator:
        current_indicator = default_indicators()
        indicators.append(current_indicator)

    # ---------- 数字输入选择公式 ----------
    if user_input.isdigit():
        idx = int(user_input) - 1
        candidates = current_indicator["formula_candidates"]
        logger.info(f"🔢 检测到候选选择 index={idx}, count={len(candidates)}")
        if 0 <= idx < len(candidates):
            chosen = candidates[idx]
            current_indicator["formula"] = chosen["FORMULAID"]
            current_indicator["indicator"] = chosen["FORMULANAME"]
            current_indicator["slot_status"]["formula"] = "filled"
            logger.info(f"✅ 用户选择公式: {current_indicator['indicator']} (FORMULAID={current_indicator['formula']})")
        else:
            logger.warning("⚠️ 用户输入的候选编号超范围: %s", user_input)
            reply = f"请输入编号 1~{len(candidates)} 选择公式。"
            graph.add_history(user_input, reply)
            graph.set_intent_info(intent_info)
            set_graph(user_id, graph)
            return reply, graph.to_state()
    # ---------- 执行查询 ----------
    if current_indicator["slot_status"]["formula"] == "filled" and current_indicator["slot_status"]["time"] == "filled":
        val, reply = await _execute_query(current_indicator)
        current_indicator["value"] = val
        current_indicator["note"] = reply
        current_indicator["status"] = "completed"
        # 必须在addNode前
        graph.set_intent_info(intent_info)
        # 写入 graph.node
        node_id = graph.add_node(current_indicator)

        # 连续判断需要找到当前intent中active的indicator，作为当前current_info传入即可
        if is_compare:
            logger.info("🔄 clarify 完成并检测到 compare 上下文，继续执行 handle_compare...")
            current_intents = [
                ind.get("indicator")
                for ind in intent_info.get("indicators")
                if ind.get("status") == "active" and ind.get("indicator")
            ]
            print(f"current_intents:{current_intents}")
            return await handle_compare(user_id, f"{user_input} -> system:完成 clarify 并检测到 compare 上下文，继续执行 handle_compare...", graph, current_intent={"candidates": current_intents})

        # 成功查询重置意图
        graph.set_intent_info({})  
        graph.add_history(user_input, reply)
        set_graph(user_id, graph)
        return reply, graph.to_state()
    reply = f"好的，要查【{current_indicator['indicator']}】，请告诉我时间。"
    graph.add_history(user_input, reply)
    current_indicator["note"] = reply
    graph.set_intent_info(intent_info)
    set_graph(user_id, graph)
    return reply, graph.to_state()

# ------------------------- 批量查询 -------------------------
async def handle_list_query(user_id: str, user_input: str, graph: ContextGraph, current_intent: dict | None = None):
    user_input = str(user_input or "").strip()
    logger.info("📋 进入 list_query，user=%s, input=%s", user_id, user_input)

    # Ensure we have a working intent_info (use snapshot recovery)
    intent_info = graph.ensure_intent_info() or {}
    intent_info.setdefault("user_input_list", []).append(user_input)
    intent_info.setdefault("intent_list", []).append("list_query，user")
    indicators = intent_info.setdefault("indicators", [])

    # Acquire candidates from current_intent if present
    candidates = []
    if current_intent and isinstance(current_intent, dict):
        candidates = current_intent.get("candidates") or []

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
    
    # replace intent indicators
    intent_info["indicators"] = parsed_indicators
    indicators = intent_info["indicators"]
    # batch
    results = []
    sids = []
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
                lines = [f"没有完全匹配的[{item["indicator"]}]指标，请从以下候选选择编号(或者重新输入尽量精确的指标名称："]
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
            sids.append(nid)
            node = graph.get_node(nid)
            ie = node.get("indicator_entry")
            item["value"] = ie.get("value")
            item["note"] = ie.get("note")
            item["status"] = "completed"
            graph.set_intent_info(intent_info)
            continue
        # else query platform
        if item["slot_status"]["formula"] == "filled" and item["slot_status"]["time"] == "filled":
            val, reply = await _execute_query(item)
            item["value"] = val
            item["note"] = reply
            item["status"] = "completed"
            # 必须在addNode前
            graph.set_intent_info(intent_info)
            # 写入 graph.node
            node_id = graph.add_node(item)
            sids.append(node_id)
        results.append(item["note"])
    # write relation and history
    graph.add_relation("group", meta={"via": "pipeline.list.query", "user_input": intent_info.get("user_input_list"), "ids": sids, "result": "\n".join(results)})
    # 成功查询重置意图
    graph.set_intent_info({})
    graph.add_history(user_input, "\n".join(results))
    set_graph(user_id, graph)
    logger.info("✅ list query 完成")
    return "\n".join(results), graph.to_state()

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
    user_input = "本月高炉工序能耗实绩报出值、计划报出值和实绩累计值分别是多少"
    current_info = await parser.parse_intent(user_input)
    print(current_info)

    # 测试批量查询
    reply, graph_state = await handle_list_query(user_id, user_input, graph, current_info)
    print("Single Query Reply 1:", reply)
    print(json.dumps(graph_state, indent=2, ensure_ascii=False))
    
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
