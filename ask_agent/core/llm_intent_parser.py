# core/llm_intent_parser.py
import logging
from core.llm_client import safe_llm_parse

logger = logging.getLogger("llm_intent_parser")
if not logger.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )

async def parse_intent(user_input: str, last_indicator: str = None, history: list = None) -> dict:
    """
    轻量意图分类（结合上下文判断）
    - user_input: 用户本次输入
    - last_indicator: 上一次查询的指标名称
    - history: 用户历史输入列表（可选）

    返回 JSON：
    {
        "intent": "ENERGY_QUERY" | "CHAT" | "TOOL" | "ENERGY_KNOWLEDGE_QA"
    }
    """
    history_summary = ""
    if history:
        recent = history[-3:]  # 最近三条
        history_summary = "\n".join([f"- {h.get('user_input')} -> {h.get('indicator')}" for h in recent])

    prompt = f"""
你是智能意图识别器，请判断用户输入属于哪类意图：

类型：
- ENERGY_QUERY: 用户想查询能源指标数值（可能需要补全时间或指标）
- CHAT: 普通知识问答或闲聊
- TOOL: 时间/日期/天气等工具类问题
- ENERGY_KNOWLEDGE_QA: 解释/定义/结构类能源知识问题

规则：
1. 如果用户输入是时间指代（如“昨天”“今天”）且 last_indicator 已存在，应识别为 ENERGY_QUERY（后续流程会补全时间）。
2. 如果用户输入明确包含指标关键词，应识别为 ENERGY_QUERY。
3. 其他非查询内容归为 CHAT 或 ENERGY_KNOWLEDGE_QA 或 TOOL。
4. 不需要返回时间或指标，只判断 intent。

输出 JSON：
{{"intent": "ENERGY_QUERY" 或 "CHAT" 或 "TOOL" 或 "ENERGY_KNOWLEDGE_QA"}}

用户输入: "{user_input}"
上一次查询指标: "{last_indicator}"
最近历史输入:\n{history_summary}
"""
    logger.info(f"🔍 [parse_intent] 用户输入: {user_input}, 上次指标: {last_indicator}")
    try:
        result = await safe_llm_parse(prompt)
        intent = result.get("intent", "CHAT")
        logger.info(f"📥 轻量意图分类结果: {intent}")
        return {"intent": intent}
    except Exception as e:
        logger.exception("❌ LLM parse_intent 调用失败: %s", e)
        return {"intent": "CHAT"}
