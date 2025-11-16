# core/llm_energy_intent_parser.py

import json
import asyncio
import logging
from core.llm_client import safe_llm_parse  # 你的安全 LLM 调用封装

logger = logging.getLogger("llm_energy_intent_parser")
if not logger.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )


class EnergyIntentParser:
    """
    能源意图解析器：
    - 统一识别用户输入的意图类型（single_query, list_query, compare, analysis, slot_fill, clarify）
    - 生成 candidates（单指标单时间查询短句）
    """

    INTENT_PROMPT = """
你是能源意图识别器，请严格返回 JSON:
{"intent":"...", "candidates":["...","..."]}

说明：
- intent 取值范围: "single_query","list_query","compare","analysis","slot_fill","clarify"。
- candidates: 将输入拆为若干“单时间单指标”短句，即拼接成“时间+指标”(时间在前，指标在后)的形式，用于后续解析指标和时间。
  例如:
  - 输入: "本月1、2号高炉工序能耗是多少"，输出: {"intent":"list_query","candidates":["本月1号高炉工序能耗","本月2号高炉工序能耗"]}。
- 指标中可能包含描述性质的后缀词（如“累计”、“计划”、“目标”、“完成值”、“用量”、“指标”、“成本”、“效率”、“总量”、“单耗”、“强度”等），可以放在每条记录最后面。
  例如:
  - 输入: "本月累计的高炉工序能耗是多少"，输出: {"intent":"single_query","candidates":["本月高炉工序能耗累计"]}。
- 指标不要随意添加和改写。1高炉就是1高炉，1#高炉就是1#高炉，**不要私自**改为1号高炉
  例如:
  - 输入: "时间：2021-10-23，1高炉工序能耗是多少"，输出: {"intent":"single_query","candidates":["2021年10月23日1高炉工序能耗"]}
  - 输入: "本月的2高炉工序能耗是多少？"，输出: {"intent":"single_query","candidates":["本月2高炉工序能耗"]}
- 如果输入是上下文补充型，但有明确时间或指标信息，请仍返回 single_query。
- 如果输入是纯对比或偏差类问题，如“它们对比呢”“偏差情况”，返回 compare。
- 如果输入中包含多个时间或多个对象，请拆分成多条 candidates。
- 如果输入的明确的肯定语气的时间信息，则表示用户在补全信息，则返回 slot_fill。

示例：

输入: "它们对比呢"
输出: {"intent":"compare","candidates":[]}

输入： "对比上月有什么变化"
输出: {"intent":"compare","candidates":["上月"]}

输入： "对比1号高炉有什么变化"
输出: {"intent":"compare","candidates":["1号高炉"]}

输入: "偏差情况"
输出: {"intent":"compare","candidates":[]}

输入: "去年呢"
输出: {"intent":"single_query","candidates":["去年"]}

输入: "去年"
输出: {"intent":"slot_fill","candidates":["去年"]}

输入: "再看酸轧能耗"
输出: {"intent":"single_query","candidates":["酸轧能耗"]}

输入: "本月高炉工序能耗是多少，对比计划偏差多少"
输出: {"intent":"compare","candidates":["本月高炉工序能耗","本月高炉工序能耗计划"]}

输入: "本年度的高炉工序能耗趋势是什么样的"
输出: {"intent":"analysis","candidates":["本年度高炉工序能耗"]}

输入: "高炉工序今天的能耗是多少"
输出: {"intent":"single_query","candidates":["今天高炉工序能耗"]}

输入: "本月1、2号高炉工序能耗偏差情况"
输出: {"intent":"compare","candidates":["本月1号高炉工序能耗","本月2号高炉工序能耗"]}
"""

    def __init__(self):
        pass

    async def parse_intent(self, user_input: str) -> dict:
        """
        使用 LLM 判断意图 + 初步分解。
        """
        try:
            # 调用 LLM
            data = await safe_llm_parse(self.INTENT_PROMPT + "\n输入: " + user_input)

            # ✅ 确保输出是 dict
            if not isinstance(data, dict):
                logger.warning(f"[parse_intent] LLM 输出非 dict，使用 fallback。输出: {data}")
                data = {}

            intent = data.get("intent")
            candidates = data.get("candidates")

            # fallback 逻辑
            if not intent:
                intent = self._fallback_intent(user_input)
            if not isinstance(candidates, list) or not candidates:
                candidates = self._fallback_candidates(user_input)

            result = {
                "intent": intent,
                "candidates": candidates
            }

            logger.info(f"[parse_intent] user_input={user_input} => {result}")
            return result

        except Exception as e:
            logger.error(f"[parse_intent] ❌ Exception: {e}")
            return {"intent": "unknown", "candidates": []}

    # --------- 内部辅助函数 ---------
    def _fallback_intent(self, user_input: str) -> str:
        """
        基于简单关键词的备选意图猜测，仅在 LLM 无法解析时使用。
        """
        if any(k in user_input for k in ["对比", "相比", "差异", "偏差", "变化"]):
            return "compare"
        if any(k in user_input for k in ["平均", "趋势"]):
            return "analysis"
        if any(k in user_input for k in ["和", "、"]):
            return "list_query"
        if any(k in user_input for k in ["呢", "去年", "今天", "补充"]):
            return "slot_fill"
        return "single_query"

    def _fallback_candidates(self, user_input: str) -> list:
        """
        简单分词分割（逗号、顿号、and、和 等）来拆分多查询。
        """
        separators = ["、", ",", "，", "和", "以及", "and"]
        for sep in separators:
            if sep in user_input:
                parts = [p.strip() for p in user_input.split(sep) if p.strip()]
                if len(parts) > 1:
                    return parts
        return [user_input]


# ========== 测试主函数 ==========
async def main():
    parser = EnergyIntentParser()

    test_inputs = [
        "高炉工序能耗是多少，对比计划偏差多少",
        "本月高炉工序能耗是多少，对比计划偏差多少",
        "今天",
        "高炉今天的工序能耗是多少",
        "本月累计的高炉工序能耗是多少",
        "1号高炉昨天的工序能耗是多少",
        "去年今天的高炉工序能耗是多少",
        "2021年10月23日的1高炉工序能耗是多少",
        "时间：2021-10-23，1高炉工序能耗是多少",
        "高炉工序能耗是多少",
        "本月1、2号高炉工序能耗是多少",
        "高炉工序能耗本月计划是多少",
        "本月高炉工序能耗的计划值是多少",
        "今天的高炉工序能耗是多少",
        "对比上月有什么变化",
        "本月的1高炉工序能耗是多少？",
        "对比2高炉有什么变化",
        "本月的高炉电耗是多少",
        "本月的高炉电使用量是多少",
        "高炉的煤气耗是多少",
        "10号高炉今天的工序能耗是多少",
        "本月的高炉工序能耗是多少？",
        "1#，2#，3#高炉分别是多少",
        "本月高炉工序能耗是多少，对比计划偏差多少",
        "本年度的高炉工序能耗趋势是什么样的",
        "本月1、2号高炉工序能耗偏差情况"
    ]

    for t in test_inputs:
        result = await parser.parse_intent(t)
        print(f"\n🧠 输入: {t}\n➡️ 解析结果: {json.dumps(result, ensure_ascii=False, indent=2)}")


if __name__ == "__main__":
    asyncio.run(main())
