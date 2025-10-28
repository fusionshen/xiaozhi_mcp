import asyncio
from core.context_graph import ContextGraph
from core.query_engine import query_multiple_indicators
from core.utils import format_reply

# 内存缓存：每个用户的上下文图谱
graph_store = {}

async def process_message(user_id: str, message: str, state: dict):
    """
    用户消息处理管线：
      1️⃣ 加载上下文图谱
      2️⃣ 调用 LLM 解析
      3️⃣ 更新上下文图谱
      4️⃣ 并行查询
      5️⃣ 生成回复
    """
    # 1️⃣ 获取或恢复上下文
    graph = graph_store.setdefault(user_id, ContextGraph.from_state(state))

    # 2️⃣ 调用 LLM 解析
    parsed = await parse_user_input(message)
    indicator = parsed.get("indicator")
    time_str = parsed.get("timeString")
    time_type = parsed.get("timeType")

    # 3️⃣ 更新图谱节点
    if indicator:
        graph.add_indicator(indicator)
    if time_str:
        graph.add_time(time_str, time_type)
    graph.link_last()

    # 4️⃣ 查询数据
    results = await query_multiple_indicators(graph)

    # 5️⃣ 生成自然语言回复
    reply = format_reply(graph, results)

    # 6️⃣ 返回结果与新状态
    return reply, graph.to_state()
