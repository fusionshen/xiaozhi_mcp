# core/intent_router.py
import logging
import time
from typing import Dict, Any

from core import llm_intent_parser as lightweight_intent    # 轻量意图分类（只判断 intent）
from core.llm_client import safe_llm_chat
from core.energy_query_runner import run_energy_query

# 日志配置（被导入时确保仅配置一次）
logger = logging.getLogger("intent_router")
if not logger.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )

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
        lightweight = await lightweight_intent.parse_intent(user_id, user_input)
        intent = (lightweight or {}).get("intent", "CHAT")
        parsed_number = (lightweight or {}).get("parsed_number", None)
        logger.info(f"🔎 轻量意图分类结果: {intent} (raw: {lightweight})")
    except Exception as e:
        logger.exception("❌ 轻量意图分类失败，退回 CHAT：%s", e)
        intent = "CHAT"
        parsed_number = None

    # ---------- Step B: 分流 ----------
    # 1) ENERGY_QUERY: 使用 EnergyIntentParser（含 context graph）
    if intent == "ENERGY_QUERY":
        logger.info("⚙️ 检测到 ENERGY_QUERY，进入能源问数流程")
        return await run_energy_query(user_id, user_input, parsed_number)

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
            return {"reply": "当前仅支持时间工具，无法解析该问题。", "error": str(e)}

    # 4) CHAT: 通用聊天由 LLM 直接回复
    else:
        logger.info("💬 检测到 CHAT 意图，转给通用聊天模型")
        try:
            chat_reply = await safe_llm_chat(user_input)
            return {"reply": chat_reply, "intent_info": {"intent": "CHAT"}}
        except Exception as e:
            logger.exception("❌ safe_llm_chat 调用失败: %s", e)
            return {"reply": "聊天服务出错。", "error": str(e)}
