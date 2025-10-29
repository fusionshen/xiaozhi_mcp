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
      2️⃣ 更新上下文节点
      3️⃣ 并行查询
      4️⃣ 生成自然语言回复
    """
    # 1️⃣ 获取或恢复上下文
    graph = graph_store.setdefault(user_id, ContextGraph.from_state(state))

    # 2️⃣ 因为 IntentParser 已经解析过，所以直接使用 graph 中最新节点
    #    pipeline 只负责 query 和格式化
    results = await query_multiple_indicators(graph)

    # 3️⃣ 生成自然语言回复
    reply = format_reply(graph, results)

    # 4️⃣ 返回结果与新状态
    return reply, graph.to_state()
