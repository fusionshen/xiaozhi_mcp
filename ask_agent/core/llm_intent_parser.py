import asyncio
import json
import re
from .llm_client import safe_llm_parse
from core.context_graph import ContextGraph

class IntentParser:
    """
    使用 LLM 解析用户意图，并结合上下文图增强多轮意图解析。
    """
    VALID_INTENTS = ["compare", "expand", "same_indicator_new_time", "list_query", "new_query"]

    def __init__(self, user_id: str):
        self.user_id = user_id
        self.history = []  # 用户输入历史 [{'user_input', 'indicator', 'timeString', 'timeType', 'intent'}]
        self.graph = ContextGraph()

    async def parse_intent(self, user_input: str):
        """
        主接口：解析用户意图，同时更新上下文图
        """
        # 构造历史上下文描述
        history_str = "\n".join(
            f"{i+1}. 输入: {h['user_input']} | 指标: {h.get('indicator')} | 时间: {h.get('timeString')} | 意图: {h.get('intent')}"
            for i, h in enumerate(self.history)
        )

        prompt = f"""
你是一个用户意图识别助手。
根据用户输入及历史对话记录判断本次输入的意图。
请严格返回 JSON：
{{"intent": "..."}}

意图说明：
- compare: 对比时间或对象
- expand: 扩展查询，例如多个对象循环调用
- same_indicator_new_time: 重复查询同一指标，仅时间变化
- list_query: 汇总或统计查询
- new_query: 新指标或全新查询

历史对话:
{history_str}

当前用户输入: "{user_input}"
"""

        result = await safe_llm_parse(prompt)
        intent = result.get("intent")
        # ------------------- 多轮意图增强 -------------------
        last_indicator = None
        for h in reversed(self.history):
            if h.get("indicator"):
                last_indicator = h["indicator"]
                break

        if intent == "new_query" and last_indicator:
            if any(kw in user_input for kw in ["昨天", "今天", "明天", "上周", "本周", "下周"]):
                intent = "same_indicator_new_time"
            elif any(kw in user_input for kw in ["和", "及", "&", ",", "对比", "比较"]):
                intent = "compare"
            elif any(kw in user_input for kw in ["平均", "总计", "统计", "汇总"]):
                intent = "list_query"

        # ------------------- 更新历史 & 图 -------------------
        record = {
            "user_input": user_input,
            "indicator": None,
            "timeString": None,
            "timeType": None,
            "intent": intent
        }
        self.history.append(record)

        return {
            "intent": intent,
            "history": self.history,
            "graph": self.graph.to_state()
        }


# ===================== 测试 =====================
if __name__ == "__main__":
    import nest_asyncio
    nest_asyncio.apply()
    loop = asyncio.get_event_loop()

    async def test():
        parser = IntentParser("user1")
        test_inputs = [
            "今天是什么日期？",
            "高炉工序能耗是多少",
            "那昨天的呢？",
            "1#和3#分别是多少",
            "平均是多少",
            "上周1#和2#比较",
            "前天晚班的吨钢用水量"
        ]
        for q in test_inputs:
            res = await parser.parse_intent(q)
            print(f"{q} => {res}")

    loop.run_until_complete(test())
