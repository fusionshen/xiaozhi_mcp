from core.llm_client import safe_llm_parse

async def parse_intent(user_input: str) -> dict:
    """
    识别用户输入的意图类型。
    可能返回：
    - ENERGY_QUERY: 与能耗、指标、数据查询相关
    - CHAT: 普通问答、知识、闲聊
    - TOOL: 时间、日期、天气等工具类问题
    """
    prompt = f"""
你是一个智能意图识别器。请判断用户输入属于哪一类：

类型定义：
- ENERGY_QUERY: 与能耗、指标、生产、公式、查询相关。
- CHAT: 普通知识问答或闲聊。
- TOOL: 涉及当前时间、日期、天气等实时信息。

输出 JSON：
{{
  "intent": "ENERGY_QUERY" 或 "CHAT" 或 "TOOL"
}}

用户输入：{user_input}
"""
    result = await safe_llm_parse(prompt)
    return result or {"intent": "CHAT"}
