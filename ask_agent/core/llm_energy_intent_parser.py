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
    能源类对话意图解析器（负责把单轮输入解析为 intent/indicator/time）。
    - 不在解析阶段持久写入 pipeline 的 ContextGraph（避免中间值污染）
    - 在 detect compare 时，会在 parser.graph 中做参考性标注（不会持久化）
    V2示例：
    | 基础问数 | 今天的高炉工序能耗是多少                                     | 1. 今天解析正确 2. 高炉工序能耗实绩报出值指标解析正确 3. 数据匹配正确 |
    | 基础问数 | 高炉今天的工序能耗是多少                                     | 1. 今天解析正确 2. 高炉工序能耗实绩报出值指标解析正确 3. 数据匹配正确 |
    | 基础问数 | 本月累计的高炉工序能耗是多少                                  | 1. 本月解析正确 2. 高炉工序能耗实绩累计值指标解析正确 3. 数据匹配正确 |
    | 基础问数 | 1号高炉昨天的工序能耗是多少                                   | 1. 昨天解析正确 2. 1号高炉工序能耗实绩报出值指标解析正确 3. 数据匹配正确 |
    | 基础问数 | 去年今天的高炉工序能耗是多少                                  | 1. 去年今天解析正确 2. 高炉工序能耗实绩报出值指标解析正确 3. 数据匹配正确 |
    | 基础问数 | 2021年10月23日的1高炉工序能耗是多少                           | 1. 2021年10月23日解析正确 2. 1高炉工序能耗实绩报出值指标解析正确 3. 数据匹配正确 |
    | 基础问数 | 时间：2021-10-23，1高炉工序能耗是多少                         | 1. 2021-10-23解析正确 2. 1高炉工序能耗实绩报出值指标解析正确 3. 数据匹配正确 |
    | 基础问数 | 高炉工序能耗是多少                                           | 1. 高炉工序能耗实绩报出值指标解析正确 2. 提示时间未指定，并默认获取上一日的数据。 |
    | 基础问数 | 本月1、2号高炉工序能耗是多少                                  | 1. 本月解析正确 2. 1高炉工序能耗实绩报出值、2高炉工序能耗实绩报出值指标解析正确 3. 两个数据匹配正确 |
    | 基础问数 | 高炉工序能耗本月计划是多少                                    | 1. 本月解析正确 2. 高炉工序能耗计划报出值指标解析正确 3. 数据匹配正确 |
    | 基础问数 | 本月高炉工序能耗的计划值是多少                                 | 1. 本月解析正确 2. 高炉工序能耗计划报出值指标解析正确 3. 数据匹配正确 |
    | 高级问数 | 本月的高炉电耗是多少                                         | 1. 本月解析正确 2. 高炉电使用量实绩单耗值指标解析正确 3. 数据匹配正确 |            
    | 高级问数 | 本月的高炉电使用量是多少                                      | 1. 本月解析正确 2. 高炉电使用量实绩爆出值指标解析正确 3. 数据匹配正确 |
    | 高级问数 | 高炉的煤气耗是多少                                           | 1. 提示有多个指标（限定：高炉，高炉煤气，单耗），让用户选择。 2. 选择指标后自动获取数据。 |
    | 高级问数 | 轮次1：本月的高炉工序能耗是多少？ 轮次2：对比上月有什么变化        | 1. 本月解析正确；上月解析正确 2. 高炉工序能耗实绩报出值指标解析正确 3. 指标对比获取数据正确，生成基础分析结论。 |
    | 高级问数 | 轮次1：本月的1高炉工序能耗是多少？ 轮次2：对比2高炉有什么变化      | 1. 本月解析正确； 2. 1高炉工序能耗实绩报出值、2高炉工序能耗实绩报出值指标解析正确 3. 指标对比获取数据正确，生成基础分析结论。 |
    | 基础问数 | 轮次1：10号高炉今天的工序能耗是多少                            | 1. 10号高炉无法匹配，提示相近的指标，并提供用户选择。 2. 选择后获取数据正确。 |
    | 高级问数 | 轮次1：本月的高炉工序能耗是多少？ 轮次2：1#，2#，3#高炉分别是多少  | 1. 本月解析正确； 2. 1高炉工序能耗实绩报出值、2高炉工序能耗实绩报出值、3高炉工序能耗实绩报出值指标解析正确 3. 指标对比获取数据正确，生成基础分析结论。 |
    | 分析报告 | 本月高炉工序能耗是多少，对比计划偏差多少                        | 1. 本月解析正确 2. 高炉工序能耗实绩报出值、高炉工序能耗计划报出值指标解析正确 3. 2个数据匹配正确，分析结论正确 |
    | 分析报告 | 本年度的高炉工序能耗趋势是什么样的                             | 1. 本月解析正确->时间段解析正确[2025-01~2025-09] 2. 高炉工序能耗实绩报出值指标解析正确 3. 数据序列匹配正确，展示数据列表正确 4. 生成趋势图正确。 5. 自动生成一段分析结论。 |
    | 分析报告 | 本月1、2号高炉工序能耗偏差情况                                | 1. 本月解析正确 2. 1高炉工序能耗实绩报出值、2高炉工序能耗实绩报出值指标解析正确 3. 2个数据匹配正确，分析结论正确 |
    """
    VALID_INTENTS = ["compare", "expand", "same_indicator_new_time", "list_query", "new_query"]

    def __init__(self, user_id: str):
        self.user_id = user_id
        self.history = []  # 解析层历史： [{'user_input','indicator','timeString','timeType','intent'}]
        self.graph = ContextGraph()  # 解析阶段参考 graph（不写回 pipeline store）
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
        关键词 fallback：只在 LLM 无法给出明确意图时使用，且不强行覆盖 LLM 返回的意图。
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
请严格返回 JSON：{{"intent": "..."}}

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
        logger.info("📤 发送能源意图识别 prompt 至 LLM")
        print(intent_prompt)
        intent_result = await safe_llm_parse(intent_prompt)
        intent = (intent_result or {}).get("intent", "new_query")
        logger.info(f"📥 LLM 返回意图识别结果: {intent_result}")

        # 指标 + 时间解析（重用 parse_user_input）
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
        logger.info(f"🧾 已追加能源指标时间解析历史记录（共 {len(self.history)} 条），注意：这不是“查询成功历史”")

        # parser 内部参考性 graph 标注（仅在有明确 compare/时间迁移时做参考）
        if enhanced_intent == "compare":
            try:
                # 若解析出 indicator/time，可以添加具体 node id（parser.graph 是参考用途）
                if indicator and timeString:
                    node_id = self.graph.add_node(indicator, timeString, timeType)
                    # 如果 parser.history 至少有上一条，则形成 relation
                    if len(self.history) >= 2:
                        prev = self.history[-2]
                        prev_id = self.graph.find_node(prev.get("indicator"), prev.get("timeString"))
                        if prev_id:
                            self.graph.add_relation("compare", source_id=prev_id, target_id=node_id)
                else:
                    # 添加无 source/target 的 compare relation 以标注意图（解析阶段）
                    self.graph.add_relation("compare")
                logger.info("🔗 parse_intent: 在 parser.graph 中记录 compare（参考）")
            except Exception as e:
                logger.warning(f"⚠️ parse_intent 添加 compare 参考失败: {e}")

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
