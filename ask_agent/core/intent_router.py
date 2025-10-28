import datetime
from core.llm_intent_parser import parse_intent
from core.llm_energy_indicator_parser import parse_user_input
from core.llm_client import safe_llm_chat

async def route_intent(user_input: str):
    """
    按意图分流处理。
    """
    intent_info = await parse_intent(user_input)
    intent = intent_info.get("intent", "CHAT")

    if intent == "ENERGY_QUERY":
        return await parse_user_input(user_input)

    elif intent == "TOOL":
        if "时间" in user_input or "几点" in user_input:
            now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            return f"当前时间是 {now}"
        else:
            return "我暂时只支持时间类工具查询。"

    else:
        return await safe_llm_chat(user_input)
