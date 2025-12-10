# app/domain/energy/ask/handlers/common.py
import re
import asyncio
import logging
import inspect
from app import core
from .. import reply_templates
from app.domains import energy as energy_domain

logger = logging.getLogger("energy.ask.handlers.common")
if not logger.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )

TOP_N = 5

# ------------------------- 辅助函数 -------------------------
def _finish(user_id: str,graph: core.ContextGraph, user_input, intent_info, reply, human_reply: str = None):
    graph.add_history(user_input, reply)
    graph.set_intent_info(intent_info)
    if intent_info == {}:
        graph.clear_main_intent()
    core.set_graph(user_id, graph)
    return reply, human_reply, graph.to_state()

async def _resolve_formula(current, graph: core.ContextGraph):
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

    resp = await asyncio.to_thread(energy_domain.formula_api.formula_query_dict, current["indicator"])
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
def _load_or_init_indicator(intent_info, graph: core.ContextGraph, allow_append: bool = True) -> dict:
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
        else:
            intent_info["indicators"] = [new_one]
        return new_one
    # 创建默认 indicator
    logger.info("⚠️ 无历史节点可用，创建默认 indicator。")
    new_default = core.default_indicators()
    indicators.append(new_default)
    return new_default

async def _execute_query(indicator_entry):
    formula = indicator_entry.get("formula")
    time_str = indicator_entry.get("timeString")
    time_type = indicator_entry.get("timeType")

    try:
        if inspect.iscoroutinefunction(energy_domain.platform_api.query_platform):
            result = await energy_domain.platform_api.query_platform(formula, time_str, time_type)
        else:
            result = await asyncio.to_thread(energy_domain.platform_api.query_platform, formula, time_str, time_type)
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
# ==== 2. 判断是否为重选场景 ====
def _is_reselect_intent(intent_info: dict, user_input: str) -> bool:
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
    return False

def _handle_formula_choice(
    current: dict,
    user_input: str,
    graph: core.ContextGraph,
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
    if is_reselect:
        updated = _update_preference_for_reselect(graph, current, current_intent)
        if updated:
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

# ---------------------
# 用户偏好反向更新（clarify 重选）
# ---------------------
def _update_preference_for_reselect(
    graph: core.ContextGraph,
    current: dict,
    current_intent: dict
) -> bool:
    """
    clarify 重选时更新用户偏好和 current。
    前置条件：
    - current_intent.get("candidates")[0] 是选中的公式编号（数字字符串）
    - current 包含当前 indicator, formula_candidates 等
    返回：
    - True 表示成功更新 current 和 preference
    - False 表示未找到匹配
    """
    try:
        if not current_intent or "candidates" not in current_intent or not current_intent["candidates"]:
            return False

        parsed_number = int(current_intent["candidates"][0])
        cands = current.get("formula_candidates") or []

        # 找到编号匹配的候选项
        matched = next((item for item in cands if int(item.get("number")) == parsed_number), None)
        if not matched:
            logger.warning(f"⚠️ 重选编号 {parsed_number} 在 formula_candidates 中未找到")
            return False

        updated = graph.update_preference(current.get("indicator"), matched)
        if updated:
            # 已更新 current 和 preference
            current["formula"] = matched["FORMULAID"]
            current["indicator"] = matched["FORMULANAME"]
            current["slot_status"]["formula"] = "filled"
            return True
        
    except Exception as e:
        logger.error(f"❌ update_preference_for_reselect 异常: {e}")
        return False