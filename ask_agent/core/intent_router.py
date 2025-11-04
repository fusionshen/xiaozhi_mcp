# core/intent_router.py
import logging
import time
from typing import Dict, Any

from core import llm_intent_parser as lightweight_intent    # 轻量意图分类（只判断 intent）
from core.llm_energy_intent_parser import EnergyIntentParser
from core.pipeline import process_message
from core.llm_client import safe_llm_chat
from agent_state import get_state, update_state

# 日志配置（被导入时确保仅配置一次）
logger = logging.getLogger("intent_router")
if not logger.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )

# 每个 user_id 对应一个 EnergyIntentParser 实例（包含上下文图谱等）
parser_store: Dict[str, EnergyIntentParser] = {}

async def route_intent(user_id: str, user_input: str) -> Dict[str, Any]:
    """
    意图路由器（V2）：
    1) 先使用轻量意图分类器判断 intent（避免重复解析）
    2) 若为 ENERGY_QUERY：使用 EnergyIntentParser.parse_intent 完成指标+时间解析并更新上下文
       然后交由 pipeline.process_message 做查询/聚合/格式化（pipeline 依赖 graph）
    3) TOOL / CHAT / ENERGY_KNOWLEDGE_QA 分流到相应处理逻辑
    返回字典包含 reply 与调试信息（intent_info / graph_state / error）
    """
    logger.info(f"🟢 [route_intent] user={user_id!r} input={user_input!r}")

    # ---------- Step A: 轻量意图判断（只返回 intent） ----------
    try:
        lightweight = await lightweight_intent.parse_intent(user_input)
        intent = (lightweight or {}).get("intent", "CHAT")
        logger.info(f"🔎 轻量意图分类结果: {intent} (raw: {lightweight})")
    except Exception as e:
        logger.exception("❌ 轻量意图分类失败，退回 CHAT：%s", e)
        intent = "CHAT"

    # ---------- Step B: 分流 ----------
    # 1) ENERGY_QUERY: 使用 EnergyIntentParser（含 context graph）
    if intent == "ENERGY_QUERY":
        logger.info("⚙️ 检测到 ENERGY_QUERY，进入能源问数流程")

        # 获取或创建 EnergyIntentParser（保存于 parser_store）
        parser = parser_store.get(user_id)
        if not parser:
            parser = EnergyIntentParser(user_id)
            parser_store[user_id] = parser
            logger.info("✨ 为用户创建新的 EnergyIntentParser（包含 ContextGraph）")
        else:
            logger.info("♻️ 复用已有 EnergyIntentParser（保留历史与 graph）")

        # 2A) 让 EnergyIntentParser 完整解析（intent + indicator + time）
        try:
            intent_info = await parser.parse_intent(user_input)
            logger.info(f"🧾 EnergyIntentParser.parse_intent 返回: intent={intent_info.get('intent')}, "
                        f"indicator={intent_info.get('indicator')}, time={intent_info.get('timeString')}")
        except Exception as e:
            logger.exception("❌ EnergyIntentParser.parse_intent 失败: %s", e)
            return {"reply": "解析能源意图失败，请稍后重试。", "error": "parse_intent_failed"}

        state = await get_state(user_id)
        state["slots"]["last_input"] = user_input
        await update_state(user_id, state)

        try:
            reply, graph_state = await process_message(user_id, user_input, parser.graph.to_state())

            logger.info("✅ pipeline.process_message 执行成功")
            # 获取 state 中的系统接口历史（成功查询记录）
            state = await get_state(user_id)
            system_history = state.get("history", [])
            last_success = system_history[-1] if system_history else {}

            # intent_info 只同步最终成功公式/指标/时间
            intent_info = {
                "intent": "new_query",
                "indicator": last_success.get("indicator"),
                "formula": last_success.get("formula"),
                "timeString": last_success.get("timeString"),
                "timeType": last_success.get("timeType"),
                "history": system_history,
                "graph": parser.graph.to_state()
            }

            return {
                "reply": reply,
                "intent_info": intent_info,
                "graph_state": graph_state
            }
        except Exception as e:
            logger.exception("❌ pipeline 执行失败: %s", e)
            return {"reply": "能源查询流程执行失败。", "error": str(e), "intent_info": intent_info}

    # 2) ENERGY_KNOWLEDGE_QA: 知识问答
    elif intent == "ENERGY_KNOWLEDGE_QA":
        logger.info("📘 检测到 ENERGY_KNOWLEDGE_QA，生成解释型回答")
        t_chat_start = time.perf_counter()
        reply = await safe_llm_chat(
            f"请能源专家身份解释以下能源知识问题：{user_input}"
        )
        t_chat_end = time.perf_counter()
        logger.info(f"🗨️ 生成成功 | ⏱️ LLM cost={1000*(t_chat_end-t_chat_start):.1f}ms")
        return {"reply": reply, "intent_info": {"intent": "ENERGY_KNOWLEDGE_QA"}}
    
    # 3) TOOL: 简单工具（例如当前时间）
    elif intent == "TOOL":
        logger.info("🛠️ 检测到 TOOL 意图，进入工具处理")

        from core.llm_time_parser import parse_time_question
        try:
            res = await parse_time_question(user_input)
            return {"reply": res["answer"], "intent_info": res}
        except Exception as e:
            logger.exception("❌ 时间问答失败: %s", e)
            return {"reply": "无法解析该时间问题。", "error": str(e)}

    # 4) CHAT: 通用聊天由 LLM 直接回复
    else:
        logger.info("💬 检测到 CHAT 意图，转给通用聊天模型")
        try:
            chat_reply = await safe_llm_chat(user_input)
            return {"reply": chat_reply, "intent_info": {"intent": "CHAT"}}
        except Exception as e:
            logger.exception("❌ safe_llm_chat 调用失败: %s", e)
            return {"reply": "聊天服务出错。", "error": str(e)}
