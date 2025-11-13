# core/energy_query_runner.py
import logging
from core.llm_energy_intent_parser import EnergyIntentParser
from core.pipeline import process_message
from core.pipeline_context import get_graph, set_graph
from core.context_graph import ContextGraph

logger = logging.getLogger("energy_query_runner")
if not logger.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )

async def run_energy_query(user_id: str, user_input: str, parsed_number: str | None):
    """
    能源查询主入口：
    - EnergyIntentParser 解析意图（无状态）
    - 将意图信息写入 ContextGraph
    - 调用 pipeline 处理
    """
    logger.info(f"⚙️ [run_energy_query] user={user_id} input={user_input!r}")

    # 获取或创建 graph
    graph = get_graph(user_id)
    if not graph:
        graph = ContextGraph()
        set_graph(user_id, graph)
        logger.info("✨ 创建新的 ContextGraph")
    else:
        logger.info("♻️ 使用已有 ContextGraph")

    # 只有在用户不是通过数字选择候选（parsed_number is None）时，才使用能源意图解析批量的candidates
    if parsed_number is None:
        # 解析意图（无状态）
        try:
            logger.info(f"🧩 传入 EnergyIntentParser.parse_intent 参数: {user_input}")
            parser = EnergyIntentParser()
            current_intent = await parser.parse_intent(user_input)
            logger.info(f"🧾 parse_intent 返回 intent={current_intent.get('intent')}")
        except Exception as e:
            logger.exception("❌ EnergyIntentParser.parse_intent 失败: %s", e)
            return {"reply": "解析能源意图失败，请稍后重试。", "error": "parse_intent_failed"}
    else:
        current_intent = {"intent":"clarify","candidates": None}
    # 不能写入 graph 中，因为可能存在clarify和slot_fill的中间态，需要把当前意图传入后续进行判断
    # graph.set_intent_info(intent_info)

    # 4️⃣ 执行主 pipeline
    try:
        reply, graph_state = await process_message(user_id, user_input, current_intent=current_intent)
        logger.info("✅ pipeline.process_message 执行成功")
        return {
            "reply": reply,
            "intent_info": ContextGraph.from_state(graph_state).get_intent_info(),
            #"graph_state": graph_state
        }

    except Exception as e:
        logger.exception("❌ pipeline 执行失败: %s", e)
        return {"reply": "能源查询流程执行失败。", "error": str(e), "intent": current_intent}
