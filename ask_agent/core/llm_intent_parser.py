# core/llm_intent_parser.py
import logging
from core.llm_client import safe_llm_parse

logger = logging.getLogger("llm_intent_parser")
if not logger.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )

async def parse_intent(user_input: str) -> dict:
    """
    轻量意图分类
    返回：
    - ENERGY_QUERY: 与能耗、指标、生产、查询相关
    - CHAT: 普通知识问答或闲聊
    - TOOL: 时间、日期、天气等工具类问题
    - ENERGY_KNOWLEDGE_QA: 解释型、定义型、结构型能源知识问题
    """
    prompt = f"""
你是智能意图识别器，请判断用户输入属于哪一类：

类型：
- ENERGY_QUERY: 与能耗、指标、生产、查询相关
- CHAT: 普通知识问答或闲聊
- TOOL: 时间、日期、天气等工具问题
- ENERGY_KNOWLEDGE_QA: 能源类解释、定义、结构、组成等知识性问题

输出 JSON：
{{"intent": "ENERGY_QUERY" 或 "CHAT" 或 "TOOL" 或 "ENERGY_KNOWLEDGE_QA"}}

用户输入：{user_input}
"""
    logger.info(f"🔍 [parse_intent] 用户输入: {user_input}")
    result = await safe_llm_parse(prompt)
    intent = (result or {}).get("intent", "CHAT")
    logger.info(f"📥 轻量意图分类结果: {intent}")
    return {"intent": intent}
