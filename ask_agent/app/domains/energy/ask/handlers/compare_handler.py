# app/domain/energy/ask/handlers/compare_handler.py
import logging
from app import core
from app.domains import energy as energy_domain
from .common import _resolve_formula, _execute_query, _finish
from .. import reply_templates

logger = logging.getLogger("energy.ask.handlers.compare")
if not logger.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )

# ------------------------- 对比、偏差 -------------------------
async def handle_compare(
        user_id: str, 
        user_input: str, 
        graph: core.ContextGraph, 
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

    # --- llm 指标扩展 ---
    last_indicator_entry = (graph.get_last_completed_node() or {}).get("indicator_entry")
    current_intent = await energy_domain.llm.expand_indicator_candidates(last_indicator_entry, current_intent)

    # --- Slot-fill 情况：无 candidates，则保持原 indicators ---
    candidates = (current_intent or {}).get("candidates") or []

    # ------------------------- 辅助局部函数 -------------------------
    async def _record_and_finish_after_compare(left_node, right_node):
        """
        记录 relation、清理 intent、写 history，并返回统一格式（reply, human_reply, state）
        reply: 机器文本简短提示
        human_reply: 人性化 Markdown（表格 + LLM 分析）
        """
        # call LLM comparator (pass the two indicator_entry objects)
        left_entry = left_node.get("indicator_entry") or {}
        right_entry = right_node.get("indicator_entry") or {}   
        analysis = await energy_domain.llm.call_compare_llm(left_entry, right_entry)
        # record relation
        graph.add_relation("compare", source_id=left_node.get("id"), target_id=right_node.get("id") ,
                           meta={"via": "pipeline.compare", "user_input": intent_info.get("user_input_list"), "result": analysis})
        return _finish(user_id, graph, user_input, {}, analysis, reply_templates.reply_compare(left_entry, right_entry, analysis))

    async def _one_step_flow():
        """
        candidates >= 2: parse前两个candidate，保证公式/time，查询（或取历史node），然后 LLM 对比
        """
        logger.info("🔎 compare: one-step 使用 candidates 解析: %s", candidates)
        parsed_items = []
        # only consider first two candidates
        for c in candidates[:2]:
            item = core.default_indicators()
            try:
                parsed = await energy_domain.llm.parse_user_input(c)
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

        node_compares = []
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
                node_compares.append(node)
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
            node_compares.append(node_obj)

        # must have two entries
        if len(node_compares) != 2:
            return _finish(user_id, graph, user_input, intent_info, "对比失败，未能获得两条有效数据。", reply_templates.reply_compare_no_data())

        return await _record_and_finish_after_compare(node_compares[0], node_compares[1])
    
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
            parsed = await energy_domain.llm.parse_user_input(candidates[0])
            for key in ("indicator", "formula", "timeString", "timeType"):
                if parsed.get(key):
                    current_indicator[key] = parsed[key]
        except Exception as e:
            logger.warning("parse_user_input 单 candidate 解析失败: %s -> %s", candidates[0], e)

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

            if base_node_id == nid:
                return _three_step_flow()

            return await _record_and_finish_after_compare(base_node_obj, node_obj)
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

            if base_node_id == nid_new:
                return _three_step_flow()

            return await _record_and_finish_after_compare(base_node_obj, new_node)

    async def _three_step_flow():
        """
        candidates == 0: use last two nodes from graph
        """
        logger.info("🔎 compare: three-step (no candidates) - 回溯 graph 最近两节点")
        if len(graph.nodes) >= 2:
            node1 = graph.nodes[-2]
            node2 = graph.nodes[-1]
            return await _record_and_finish_after_compare(node1, node2)

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