# core/llm_intent_parser.py
import logging
from core.llm_client import safe_llm_parse
from agent_state import get_state

logger = logging.getLogger("llm_intent_parser")
if not logger.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )

async def parse_intent(user_id: str, user_input: str) -> dict:
    """
    轻量意图分类（结合上下文与候选状态判断）
    - user_input: 用户本次输入
    - last_indicator: 上一次查询的指标名称
    - history: 用户历史输入列表（成功查询）
    - slots: 当前状态槽位，包括 awaiting_confirmation / formula_candidates 等
    
    返回 JSON：
    {
        "intent": "ENERGY_QUERY" | "CHAT" | "TOOL" | "ENERGY_KNOWLEDGE_QA"
    }
    """
    # 获取 state 中的系统接口历史（成功查询记录）
    state = await get_state(user_id)
    history = state.get("history", [])
    slots = state.get("slots", [])
    last_success = history[-1] if history else {}
    last_indicator = last_success.get("indicator")
    # 最近历史摘要
    history_summary = ""
    if history:
        recent = history[-3:]
        history_summary = "\n".join([
            f"- {h.get('user_input')} -> {h.get('indicator')}" for h in recent
        ])

    # 槽位状态摘要
    slots_summary = ""
    if slots:
        slots_summary = "\n".join([
            f"{k}: {v}" for k, v in slots.items()
            if k in ["awaiting_confirmation", "formula_candidates", "indicator", "formula", "timeString"]
        ])

    prompt = f"""
你是一个智能意图识别器。请判断当前用户输入属于哪类意图。

意图类型：
- ENERGY_QUERY: 用户想查询能源指标数据（包括初次查询、补充时间、或正在选择候选公式）
- CHAT: 普通闲聊或非结构化提问
- TOOL: 工具类问题（时间、日期、天气等）
- ENERGY_KNOWLEDGE_QA: 解释能源概念或定义的问题

当前上下文：
- 用户输入: "{user_input}"
- 上次查询指标: "{last_indicator}"
- 最近成功查询记录:
{history_summary if history_summary else '(无)'}
- 当前系统槽位状态:
{slots_summary if slots_summary else '(空)'}

识别规则（优先级从高到低）：
1. 如果用户正在选择候选公式（awaiting_confirmation=True 且 formula_candidates 存在）：
   - 输入为数字或序号指代（如“1”“第二个”） → ENERGY_QUERY。
   - 输入与能源无关 → CHAT。
2. 如果当前处于能源查询流程（awaiting_confirmation=True 或 indicator 存在），
   且用户输入包含时间表达（如“今天”“昨天”“2022年的今天”“上月”），
   则视为 ENERGY_QUERY —— 表示用户在补充查询时间，而不是单纯问时间。
3. 如果用户输入包含能源指标、单位、能耗类词汇（如“电耗”“高炉煤气使用量”），
   视为 ENERGY_QUERY。
4. 如果用户提问能源定义、概念、用途 → ENERGY_KNOWLEDGE_QA。
5. 如果输入与能源查询流程无关且是日期、时间、天气类问题 → TOOL。
6. 其他普通问答 → CHAT。

请返回一个 JSON：
{{
  "intent": "ENERGY_QUERY" 或 "CHAT" 或 "TOOL" 或 "ENERGY_KNOWLEDGE_QA",
  "parsed_number": 如果用户输入的是候选编号或“选第一条”等，请提取数字编号（整数），否则为 null
}}
"""

    
    logger.info(f"🔍 [parse_intent] 用户输入: {user_input}, 上次指标: {last_indicator}, awaiting={slots.get('awaiting_confirmation') if slots else None}")
    try:
        result = await safe_llm_parse(prompt)
        intent = result.get("intent", "CHAT")
        parsed_number = result.get("parsed_number")
        logger.info(f"📥 轻量意图分类结果: {intent}, parsed_number={parsed_number}")
        return {"intent": intent, "parsed_number": parsed_number}
    except Exception as e:
        logger.exception("❌ LLM parse_intent 调用失败: %s", e)
        return {"intent": "CHAT", "parsed_number": None}
