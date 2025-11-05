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
    - 负责把单轮用户输入解析为 intent/indicator/time（用于后续 pipeline 补全）
    - 解析器的 history 保存解析轨迹（不是系统成功查询的 history）
    - 不在解析阶段把未确认的解析结果写入 ContextGraph，避免污染
    """
    VALID_INTENTS = ["compare", "expand", "same_indicator_new_time", "list_query", "new_query"]

    def __init__(self, user_id: str):
        self.user_id = user_id
        # parser 的解析历史（用于构造 prompt）
        self.history = []  # [{'user_input', 'indicator', 'timeString', 'timeType', 'intent'}]
        # parser 内部保留一个 graph 对象供参考（但不主动写入）
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
        """
        关键词 fallback：只在 LLM 无法给出明确意图时使用，
        并且不强行覆盖 LLM 返回的意图。
        """
        logger.debug(f"🔍 关键词 fallback: 原始意图={intent}, last_indicator={last_indicator}, input={user_input}")
        if intent in [None, "new_query"] and last_indicator:
            if any(kw in user_input for kw in ["昨天", "今天", "明天", "上周", "本周", "下周", "上月", "上季度"]):
                intent = intent or "same_indicator_new_time"
                logger.debug("🟡 关键词 fallback: 检测到时间相关词，设为 same_indicator_new_time")
            elif any(kw in user_input for kw in ["和", "及", "&", ",", "对比", "比较", "相比"]):
                intent = intent or "compare"
                logger.debug("🟡 关键词 fallback: 检测到对比词，设为 compare")
            elif any(kw in user_input for kw in ["平均", "总计", "统计", "汇总"]):
                intent = intent or "list_query"
                logger.debug("🟡 关键词 fallback: 检测到汇总词，设为 list_query")
        logger.debug(f"✅ 最终 fallback 意图={intent}")
        return intent

    async def parse_intent(self, user_input: str):
        """
        1) 调用 LLM 判断意图（compare/expand/.../new_query）
        2) 调用 parse_user_input 抽取 indicator/time（仅用于补全 slots）
        3) 将解析记录追加到 parser.history（注意：这不是系统级成功 history）
        返回：{intent, indicator, timeString, timeType, history, graph}
        """
        logger.info(f"🧠 [parse_intent] user={self.user_id} | input={user_input}")

        # Step 1: 格式化历史供 prompt 使用
        history_str = self._format_history_for_prompt()

        # Step 2: LLM 判断意图
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

        # Step 3: 指标 + 时间解析（重用 parse_user_input）
        try:
            parsed_info = await parse_user_input(user_input)
            logger.info(f"📊 指标解析结果: {parsed_info}")
        except Exception as e:
            logger.exception("⚠️ 指标解析失败，返回空值: %s", e)
            parsed_info = {"indicator": None, "timeString": None, "timeType": None}

        indicator = parsed_info.get("indicator")
        timeString = parsed_info.get("timeString")
        timeType = parsed_info.get("timeType")

        # Step 4: 轻量 fallback（仅在 LLM 结果不明确或为 new_query 且存在 last_indicator 时使用）
        last_indicator = next((h["indicator"] for h in reversed(self.history) if h.get("indicator")), None)
        enhanced_intent = self._enhance_intent_by_keywords(intent, user_input, last_indicator)
        logger.info(f"🎯 最终意图确定: {enhanced_intent}")

        # Step 5: 追加解析历史（仅解析层面）
        record = {
            "user_input": user_input,
            "indicator": indicator,
            "timeString": timeString,
            "timeType": timeType,
            "intent": enhanced_intent
        }
        self.history.append(record)
        logger.info(f"🧾 已追加解析历史记录（共 {len(self.history)} 条），注意：这不是“查询成功历史”")

        # Step 6: 如果是 compare，尝试识别 source/target
        if enhanced_intent == "compare":
            logger.info("🔍 检测到 compare 意图，准备建立对比关系")

            # 至少需要两条历史记录
            if len(self.history) >= 2:
                source = self.history[-2]
                target = self.history[-1]
                self.graph.add_relation("compare", source, target)
                logger.info(f"🔗 已记录对比关系: {source['user_input']} vs {target['user_input']}")
            else:
                logger.warning("⚠️ compare 意图但历史不足两条，无法建立关系")


        # 返回解析结果（graph 为参考当前 parser.graph state）
        result = {
            "intent": enhanced_intent,
            "indicator": indicator,
            "timeString": timeString,
            "timeType": timeType,
            "history": self.history,
            "graph": self.graph.to_state()
        }
        logger.info(f"✅ parse_intent 完成，返回结果: intent={enhanced_intent}, indicator={indicator}, time={timeString}")
        return result


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
            print(f"{q} => {res['intent']}")

    loop.run_until_complete(test())
