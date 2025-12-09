from core.graph_manager import set_graph, get_graph, remove_graph
from core.context_graph import ContextGraph
from domains.energy.ask.pipeline_handlers import handle_single_query, handle_compare
from domains.energy.services import formula_api
import asyncio

async def main():
    # 只初始化一次，不会重复加载
    formula_api.initialize()

    user_id = "test_user"
    remove_graph(user_id)  # 清理旧图谱
    graph = get_graph(user_id) or ContextGraph()
    set_graph(user_id, graph)

    # 测试单指标查询
    reply, _, _ = await handle_single_query(user_id, "2022年3月的1#高炉工序能耗是多少？", graph)
    print("Single Query Reply:", reply)

    reply2, _, _ = await handle_single_query(user_id, "2#高炉工序能耗呢", graph)
    print("Single Query Reply2:", reply2)

    from domains.energy.llm.llm_energy_intent_parser import EnergyIntentParser
    parser = EnergyIntentParser()
    user_input = "它们对比呢"
    current_info = await parser.parse_intent(user_input)
    print(current_info)

    # 测试三步对比
    reply3, _, _ = await handle_compare(user_id, user_input, graph, current_info)
    print("Single Query Reply 3:", reply3)
    

    # 测试一步对比
    # reply, _, graph_state = await handle_compare(user_id, user_input, graph, current_info)
    # print("Single Query Reply:", reply)
    # print(json.dumps(graph_state, indent=2, ensure_ascii=False))

    # # 测试选择备选
    # reply, graph_state = await handle_clarify(user_id, 1, graph)
    # print("Single Query Reply 2:", reply)
    # print(json.dumps(graph_state, indent=2, ensure_ascii=False))

    # # # 测试补齐时间
    # reply, graph_state = await handle_slot_fill(user_id, "今天", graph, {"candidates": ["今天"]})
    # print("Single Query Reply 3:", reply)
    # print(json.dumps(graph_state, indent=2, ensure_ascii=False))

    # # 测试问另外的时间
    # reply, graph_state = await handle_slot_fill(user_id, "哪昨天呢？", graph, {"candidates": ["昨天"]})
    # print("Single Query Reply 4:", reply)
    # print(json.dumps(graph_state, indent=2, ensure_ascii=False))
    
    # 再查询一个指标（可测试对比）
    # msg2 = "昨天高炉工序能耗是多少"
    # reply2, graph_state2 = await handle_single_query(user_id, msg2, graph)
    # print("Single Query Reply 2:", reply2)
    # print(json.dumps(graph_state2, indent=2, ensure_ascii=False))

    # # 对比
    # cmp_reply, _ = await handle_compare(user_id, "对比最新两条数据", graph)
    # print("Compare Reply:", cmp_reply)


if __name__ == "__main__":
    asyncio.run(main())