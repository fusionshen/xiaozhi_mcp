# test_llm_intent_parser.py
import asyncio
from datetime import datetime
from core.llm_intent_parser import parse_intent  # 待实现
from agent_state import get_state, update_state

# 模拟用户ID
USER_ID = "user_test_01"

# 初始化 event loop
import nest_asyncio
nest_asyncio.apply()
loop = asyncio.get_event_loop()

# 测试用例列表：每个元素是 (用户输入, 期望意图)
test_cases = [
    ("今天是什么日期？", "ask_time"),
    ("高炉工序能耗是多少", "new_query"),
    ("那昨天的呢？", "same_indicator_new_time"),
    ("对比上周", "compare"),
    ("1#、2#、3#分别是多少", "expand"),
    ("平均是多少", "list_query"),
    ("明天的高炉电耗是多少", "same_indicator_new_time"),
    ("单位是什么？", "list_query"),
    ("下周的吨钢用水量和本周对比", "compare")
]

async def run_test():
    for user_input, expected_intent in test_cases:
        # 调用 llm_intent_parser 解析意图
        intent_result = await parse_intent(USER_ID, user_input)
        
        # 更新 agent_state，模拟连续对话
        update_state(USER_ID, {
            "last_query": {
                "user_input": user_input,
                "intent": intent_result.get("intent"),
                "timeString": intent_result.get("timeString"),
                "indicator": intent_result.get("indicator")
            }
        })
        
        print(f"用户输入: {user_input}")
        print(f"解析意图: {intent_result.get('intent')} (期望: {expected_intent})")
        print(f"解析详情: {intent_result}\n")

if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    loop.run_until_complete(run_test())
