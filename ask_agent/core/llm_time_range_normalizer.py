# core/llm_time_range_normalizer.py

from datetime import datetime
from core.llm_client import safe_llm_parse


"""
normalize_time_range(timeString, timeType)

用途：
- 当 timeString 不是 range（不包含 "~"）时，自动让 LLM 将其扩展为 range。
- 所有区间推算（如 YEAR -> 本年 1 月 ~ 当前月）全部由 LLM 决定。
- timeType 降级（MONTH->DAY、YEAR->MONTH、WEEK->DAY…）也由 LLM 统一返回。

返回格式（严格）：
{
    "timeString": "xxxx~xxxx",
    "timeType": "DAY/MONTH/..."
}

降级规则（需传给 LLM）：
["HOUR","SHIFT","DAY","WEEK","MONTH","QUARTER","TENDAYS","YEAR"]
SHIFT/HOUR → 不降级
YEAR → MONTH
QUARTER → MONTH
TENDAYS → DAY
MONTH → DAY
WEEK → DAY
DAY → DAY
"""


def _make_prompt(timeString: str, timeType: str, now: datetime) -> str:
    now_str = now.strftime("%Y-%m-%d %H:%M")

    return f"""
你是一个“时间范围标准化助手”。你的任务是根据输入的 timeString 与 timeType，
返回一个“已经被扩展为明确范围的时间区间”。

系统当前时间：{now_str}

你必须严格遵守以下规则，不允许推理扩展、覆盖、模糊处理。

======================================================================
【最高优先级强制约束 —— 不得被任何规则、示例、推理覆盖】
以下类型属于系统最小粒度，禁止展开范围、禁止降级、禁止区间推算：

1. timeType = "HOUR"
2. timeType = "SHIFT"

如果输入 timeType 是以上任意一种：
你必须直接原样返回：

{{
    "timeString": "原样输入的 timeString",
    "timeType": "原样输入的 timeType"
}}

你不得对 HOUR 或 SHIFT 做任何生成、猜测、补全或范围扩展。
======================================================================

【强制降级规则 —— 你必须执行，不允许忽略】
（以下规则优先级高于区间扩展规则）

可降级类型：
- YEAR → MONTH
- QUARTER → MONTH
- MONTH → DAY
- TENDAYS → DAY
- WEEK → DAY
- DAY → HOUR   （仅结构化，不扩展到 00~23）
  - 注意：DAY → HOUR 与 HOUR 不冲突，因为 DAY 仍不是最小粒度
  - 但你不得创造“具体小时范围”（例如 00~23），因为小时属于用户自己输入的粒度

禁止降级：
- HOUR（最小粒度）
- SHIFT（最小粒度）
======================================================================
【区间扩展规则（仅当 timeString 不包含 "~" 时）】

如果 timeString 不包含 "~"，说明用户输入的是“点”，所有扩展都依赖系统当前时间。

你需要基于 timeType 的自然含义，结合系统当前系统时间 {now_str}，生成一个区间。
各种类型的扩展方式如下：

1. YEAR
   - 如果输入时间为 "2024"
      - 如当前系统时间也在 2024年，则输出 2024-01~2024-当前月
   - 如果输入年份与当前系统年份不同
      - 你必须输出完整自然年区间：YYYY-01~YYYY-12
   - 降级为 MONTH

2. QUARTER
   - 如果输入时间为 "2025-Q2"
    - 应输出对应该季度的范围2025-04~2025-06
   - 扩展为该季度的自然月份范围（如 Q1 → 01~03 Q2 → 04~06 Q3 → 07~09 Q4 → 10~12）
   - 降级为 "MONTH"

3. MONTH
   - 扩展为整月自然天范围（2023-06-01~2023-06-30）
   - 扩展后你必须把 timeType 改为 DAY

4. WEEK
   - 如果输入时间为 "2025-W15"
   - 扩展为该周的自然日期区间（周一到周日）
   - 降级为 "DAY"

5. TENDAYS（上旬/中旬/下旬）
   - 如果输入时间为 "2025-10上旬"
    - 应输出对应的天数范围2025-10-01~2025-10-10
   - 根据自然日进行扩展（如上旬是1~10日，中旬是11~20日，下旬是21~月底）
   - 降级为 "DAY"

6. DAY
   - 如果输入时间为 "2024-10-03"
   - 应输出 2024-10-03 00~2024-10-03 23
   - 降级为 "HOUR"

7. 如果 timeString 本身已有 "~"，则视为用户显式范围：不得修改、不得降级
======================================================================
【最终输出格式】
你必须返回 JSON：

{{
    "timeString": "...~...",
    "timeType": "..."
}}

或（当 timeType 为 HOUR/SHIFT 时）：

{{
    "timeString": "原样输入的 timeString",
    "timeType": "原样输入的 timeType"
}}

======================================================================

【必须遵守的行为规范】

- 所有字段必须保持全大写（如 YEAR/MONTH/WEEK）。
- 不允许输出额外字段。
- 不允许输出解释、注释，只能输出 JSON。
- 不允许生成你自行构造的时间（除自然扩展与基于系统时间的必要推算）。
- 不允许扩大 HOUR/SHIFT 的范围。

用户输入："timeString":"{timeString}" , "timeType":"{timeType}" 
"""


async def normalize_time_range(timeString: str, timeType: str, now: datetime = None):
    """
    输入：
        timeString: "2025" / "2024-08" / "2025-W31" / "昨天" ...
        timeType: "YEAR" / "MONTH" / "DAY" / "WEEK" / ...

    输出（完全由 LLM 决定）：
        {
            "timeString": "....~....",
            "timeType": "MONTH/DAY/HOUR"
        }
    """
    if now is None:
        now = datetime.now()

    # 已经是范围，不处理
    if "~" in timeString:
        return {
            "timeString": timeString,
            "timeType": timeType
        }

    prompt = _make_prompt(timeString, timeType, now)

    # 交给 LLM 处理所有逻辑
    res = await safe_llm_parse(prompt)

    # LLM 已保证返回 JSON
    return res
