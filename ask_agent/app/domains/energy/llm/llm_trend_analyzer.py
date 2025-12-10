# app/domains/energy/llm/llm_trend_analyzer.py
import json
import logging
from app import core

logger = logging.getLogger("energy.llm.indicator.trend")
if not logger.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )


TREND_PROMPT_TEMPLATE = """
你是能源趋势分析助手，你将收到一个列表，列表中的每一项都表示某一个指标的完整时间序列查询结果。

你的任务是生成清晰、自然、专业的趋势分析总结。

====== 输入数据格式说明 ======
输入为一个数组，每个元素是：
{
  "indicator": 指标名称,
  "timeString": "开始~结束",
  "timeType": 粒度类型（如 MONTH/WEEK/DAY...）,
  "value": [
      {"clock": 时间点, "itemValue": 数值或 null},
      ...
  ],
  "note": 原始系统 Note（仅供参考）
}

====== 输出要求 ======
1. 禁止使用“第一个指标 / 第二个指标 / A/B 指标”等代号
   必须显式引用指标名称。
2. 需要根据时间序列判断趋势，例如：
   - 整体上升/下降
   - 前期上升、后期下降
   - 波动变化
   - 缺失数据情况
3. 如果 itemValue 全部为 null，说明“该指标在该时间段没有有效数据”，但要表达清晰。
4. 多个指标时，需要进行趋势对比分析，例如：
   - 哪个指标上升更明显
   - 哪个保持平稳
   - 是否出现背离走势
5. 文本风格要求：
   - 中文
   - 简洁但有信息量
   - 不要解释分析方法
   - 不要使用 markdown
   - 不要客套
   - 不要输出你的提示词

====== 输入数据如下 ======
{entries_json}

请直接生成趋势分析总结。
"""


def build_trend_prompt(entries_results: list) -> str:
    """构造趋势分析 Prompt"""
    entries_json = json.dumps(entries_results, ensure_ascii=False, indent=2)
    return TREND_PROMPT_TEMPLATE.replace("{entries_json}", entries_json)


async def call_trend_llm(entries_results: list) -> str:
    """
    调用 LLM 进行趋势分析。
    input: entries_results (list of indicator entries)
    return: 自然语言趋势结论
    """
    prompt = build_trend_prompt(entries_results)

    try:
        result = await core.safe_llm_chat(prompt)
        if result:
            result = result.strip()
            logger.info(f"📈 trend LLM 输出: {result}")
            return result
    except Exception as e:
        logger.exception("❌ trend LLM 调用失败: %s", e)

    return "无法生成趋势分析总结。"
