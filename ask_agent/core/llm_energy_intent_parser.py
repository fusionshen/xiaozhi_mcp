# core/llm_energy_intent_parser.py

import asyncio
import logging
from core.llm_client import safe_llm_parse
from core.context_graph import ContextGraph
from core.llm_energy_indicator_parser import parse_user_input

logger = logging.getLogger("llm_energy_intent_parser")
if not logger.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )

class EnergyIntentParser:
    """
    能源类对话解析器：
    处理 ENERGY_QUERY 类型的用户输入，提取指标、时间并更新多轮上下文图。
    使用 ContextGraph 的 nodes 确保去重。
    """
    VALID_INTENTS = ["compare", "expand", "same_indicator_new_time", "list_query", "new_query"]

    def __init__(self, user_id: str):
        self.user_id = user_id
        self.history = []  # [{'user_input', 'indicator', 'timeString', 'timeType', 'intent'}]
        self.graph = ContextGraph()
        logger.info(f"🧩 初始化 EnergyIntentParser for user={user_id}")

    def _format_history_for_prompt(self):
        formatted = "\n".join(
            f"{i+1}. 输入: {h['user_input']} | 指标: {h.get('indicator')} | 时间: {h.get('timeString')} | 意图: {h.get('intent')}"
            for i, h in enumerate(self.history)
        )
        logger.debug(f"📜 格式化历史记录:\n{formatted}")
        return formatted

    def _enhance_intent_by_keywords(self, intent, user_input, last_indicator):
        logger.debug(f"🔍 关键词增强: 原始意图={intent}, last_indicator={last_indicator}, input={user_input}")
        if intent == "new_query" and last_indicator:
            if any(kw in user_input for kw in ["昨天", "今天", "明天", "上周", "本周", "下周"]):
                intent = "same_indicator_new_time"
            elif any(kw in user_input for kw in ["和", "及", "&", ",", "对比", "比较"]):
                intent = "compare"
            elif any(kw in user_input for kw in ["平均", "总计", "统计", "汇总"]):
                intent = "list_query"
        logger.debug(f"✅ 增强后意图={intent}")
        return intent

    async def parse_intent(self, user_input: str):
        logger.info(f"🧠 [parse_intent] user={self.user_id} | input={user_input}")

        # Step 1: 历史上下文
        history_str = self._format_history_for_prompt()

        # Step 2: 调用 LLM 判断意图
        intent_prompt = f"""
你是一个用户意图识别助手。
根据用户输入及历史对话记录判断本次输入的意图。
请严格返回 JSON：
{{"intent": "..."}}

意图说明：
- compare: 对比时间或对象
- expand: 扩展查询
- same_indicator_new_time: 同指标不同时间
- list_query: 汇总统计
- new_query: 新指标或新问题

历史对话:
{history_str}

当前用户输入: "{user_input}"
"""
        logger.info("📤 发送意图识别 prompt 至 LLM")
        intent_result = await safe_llm_parse(intent_prompt)
        intent = intent_result.get("intent", "new_query")
        logger.info(f"📥 LLM 返回意图识别结果: {intent_result}")

        # Step 3: 指标 + 时间解析
        try:
            parsed_info = await parse_user_input(user_input)
            logger.info(f"📊 指标解析结果: {parsed_info}")
        except Exception as e:
            logger.exception("⚠️ 指标解析失败，返回空值: %s", e)
            parsed_info = {"indicator": None, "timeString": None, "timeType": None}

        indicator = parsed_info.get("indicator")
        timeString = parsed_info.get("timeString")
        timeType = parsed_info.get("timeType")

        # Step 4: 多轮增强
        last_indicator = next((h["indicator"] for h in reversed(self.history) if h.get("indicator")), None)
        enhanced_intent = self._enhance_intent_by_keywords(intent, user_input, last_indicator)
        logger.info(f"🎯 最终意图确定: {enhanced_intent}")

        # Step 5: 更新上下文图与历史
        # ✅ 使用 nodes 去重，同时同步更新 indicators 和 times
        self.graph.add_node(indicator, timeString, timeType)

        # 追加历史记录
        record = {
            "user_input": user_input,
            "indicator": indicator,
            "timeString": timeString,
            "timeType": timeType,
            "intent": enhanced_intent
        }
        self.history.append(record)
        logger.info(f"🧾 已追加历史记录（共 {len(self.history)} 条）")

        return {
            "intent": enhanced_intent,
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
        parser = EnergyIntentParser("user1")
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
