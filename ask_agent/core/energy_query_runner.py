# core/energy_query_runner.py
import logging
from typing import Dict, Any
from agent_state import get_state, update_state
from core.pipeline import process_message
from core.llm_energy_intent_parser import EnergyIntentParser

logger = logging.getLogger("energy_query_runner")
if not logger.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )

# 每个 user_id 对应一个 EnergyIntentParser 实例（包含上下文图谱等）
parser_store: Dict[str, EnergyIntentParser] = {}

async def run_energy_query(user_id: str, user_input: str, parsed_number: str | None):
    """
    能源问数主流程：
    1. 获取或创建 EnergyIntentParser
    2. 根据是否为候选编号选择输入
    3. 执行 parse_intent + pipeline.process_message
    4. 返回 reply / intent_info / graph_state
    """
    logger.info("⚙️ [run_energy_query] 开始执行 ENERGY_QUERY 流程")

    # 1️⃣ 获取或创建解析器
    parser = parser_store.get(user_id)
    if not parser:
        parser = EnergyIntentParser(user_id)
        parser_store[user_id] = parser
        logger.info("✨ 创建新的 EnergyIntentParser（含 ContextGraph）")
    else:
        logger.info("♻️ 复用已有 EnergyIntentParser（保留历史与 graph）")

    state = await get_state(user_id)
    slots = state.setdefault("slots", {})
    slots["last_input"] = user_input

    # 只有在用户不是通过数字选择候选（parsed_number is None）时，才用 parser 返回的 intent 更新 slots
    if parsed_number is None:
        # 2️⃣ 解析意图输入
        try:
            logger.info(f"🧩 传入 EnergyIntentParser.parse_intent 参数: {user_input}")
            intent_info = await parser.parse_intent(user_input)
            logger.info(f"🧾 parse_intent 返回 intent={intent_info.get('intent')}")
            slots["intent"] = intent_info.get('intent') or "new_query"
        except Exception as e:
            logger.exception("❌ EnergyIntentParser.parse_intent 失败: %s", e)
            return {"reply": "解析能源意图失败，请稍后重试。", "error": "parse_intent_failed"}
    else:
        # 反之将识别后的数字传入, process_message 开头就会判断
        user_input = parsed_number if parsed_number is not None else user_input

    # 3️⃣ 更新 state
    await update_state(user_id, state)

    # 4️⃣ 执行主 pipeline
    try:
        reply, graph_state = await process_message(user_id, user_input, parser.graph.to_state())
        logger.info("✅ pipeline.process_message 执行成功")

        # 5️⃣ 构造 intent_info
        state = await get_state(user_id)
        slots = state.get("slots", {})
        
        # 获取 state 中的系统接口历史（成功查询记录）
        system_history = state.get("history", [])
        last_success = system_history[-1] if system_history else {}

        # ✅ 判断是否在等待用户确认候选公式
        if slots.get("awaiting_confirmation"):
            intent_info = {
                "awaiting_confirmation": True,
                "formula_candidates": slots.get("formula_candidates"),
                "intent": slots.get("intent"),
                "indicator": slots.get("indicator"),
                "formula": slots.get("formula"),
                "timeString": slots.get("timeString"),
                "timeType": slots.get("timeType"),
                "history": system_history
            }
        else:
            # 默认路径：直接取最后成功的查询
            intent_info = {
                "intent": last_success.get('intent'),
                "indicator": last_success.get("indicator"),
                "formula": last_success.get("formula"),
                "timeString": last_success.get("timeString"),
                "timeType": last_success.get("timeType"),
                "history": system_history
            }

        return {
            "reply": reply,
            "intent_info": intent_info,
            "graph_state": graph_state
        }

    except Exception as e:
        logger.exception("❌ pipeline 执行失败: %s", e)
        return {"reply": "能源查询流程执行失败。", "error": str(e), "intent_info": intent_info}
