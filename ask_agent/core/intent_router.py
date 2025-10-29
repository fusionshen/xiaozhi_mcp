from core.llm_energy_intent_parser import IntentParser
from core.pipeline import process_message
from core.llm_client import safe_llm_chat
from core.context_graph import ContextGraph

# 内存缓存每个用户的 IntentParser
parser_store = {}

async def route_intent(user_id: str, user_input: str):
    """
    按意图分流处理。
    """
    # 获取或创建 IntentParser
    parser = parser_store.get(user_id)
    if not parser:
        parser = IntentParser(user_id)
        parser_store[user_id] = parser

    # 解析意图 + 指标 + 时间
    intent_info = await parser.parse_intent(user_input)
    intent = intent_info.get("intent", "CHAT")

    if intent == "ENERGY_QUERY":
        # 使用 pipeline 处理完整流程
        reply, graph_state = await process_message(user_id, user_input, parser.graph.to_state())
        return {
            "reply": reply,
            "intent_info": intent_info,
            "graph_state": graph_state
        }

    elif intent == "TOOL":
        # 简单工具逻辑
        if "时间" in user_input or "几点" in user_input:
            import datetime
            now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            return {"reply": f"当前时间是 {now}"}
        else:
            return {"reply": "我暂时只支持时间类工具查询。"}

    else:
        # 默认聊天
        chat_reply = await safe_llm_chat(user_input)
        return {"reply": chat_reply, "intent_info": intent_info}
