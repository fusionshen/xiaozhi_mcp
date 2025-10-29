# core/llm_energy_intent_parser.py

import asyncio
from core.llm_client import safe_llm_parse
from core.context_graph import ContextGraph
from core.llm_energy_indicator_parser import parse_user_input  # ✅ 复用你的旧解析逻辑


class IntentParser:
    """
    使用 LLM 解析用户意图 + 指标 + 时间，支持多轮上下文。
    """
    VALID_INTENTS = ["compare", "expand", "same_indicator_new_time", "list_query", "new_query"]

    def __init__(self, user_id: str):
        self.user_id = user_id
        self.history = []  # [{'user_input', 'indicator', 'timeString', 'timeType', 'intent'}]
        self.graph = ContextGraph()

    def _format_history_for_prompt(self):
        return "\n".join(
            f"{i+1}. 输入: {h['user_input']} | 指标: {h.get('indicator')} | 时间: {h.get('timeString')} | 意图: {h.get('intent')}"
            for i, h in enumerate(self.history)
        )

    def _enhance_intent_by_keywords(self, intent, user_input, last_indicator):
        # 基于关键词进行多轮意图增强
        if intent == "new_query" and last_indicator:
            if any(kw in user_input for kw in ["昨天", "今天", "明天", "上周", "本周", "下周"]):
                intent = "same_indicator_new_time"
            elif any(kw in user_input for kw in ["和", "及", "&", ",", "对比", "比较"]):
                intent = "compare"
            elif any(kw in user_input for kw in ["平均", "总计", "统计", "汇总"]):
                intent = "list_query"
        return intent

    async def parse_intent(self, user_input: str):
        """
        主接口：解析用户意图、指标、时间，同时更新上下文图
        """
        # ===== 第一步：构造上下文描述 =====
        history_str = self._format_history_for_prompt()

        # ===== 第二步：LLM 判断意图 =====
        intent_prompt = f"""
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
        intent_result = await safe_llm_parse(intent_prompt)
        intent = intent_result.get("intent", "new_query")

        # ===== 第三步：调用 llm_parser 抽取指标 + 时间 =====
        try:
            parsed_info = await parse_user_input(user_input)
        except Exception as e:
            print("⚠️ llm_parser 调用失败:", e)
            parsed_info = {"indicator": None, "timeString": None, "timeType": None}

        indicator = parsed_info.get("indicator")
        timeString = parsed_info.get("timeString")
        timeType = parsed_info.get("timeType")

        # ===== 第四步：多轮增强逻辑 =====
        last_indicator = next((h["indicator"] for h in reversed(self.history) if h.get("indicator")), None)
        intent = self._enhance_intent_by_keywords(intent, user_input, last_indicator)

        # ===== 第五步：更新上下文图与历史 =====
        self.graph.add_node(indicator, timeString, timeType)

        record = {
            "user_input": user_input,
            "indicator": indicator,
            "timeString": timeString,
            "timeType": timeType,
            "intent": intent
        }
        self.history.append(record)

        return {
            "intent": intent,
            "indicator": indicator,
            "timeString": timeString,
            "timeType": timeType,
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
