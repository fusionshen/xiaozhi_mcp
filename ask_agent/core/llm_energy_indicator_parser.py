# core/llm_energy_indicator_parser.py
import asyncio
import re
from datetime import datetime
from core.llm_client import safe_llm_parse


"""
在无示例情况下，如果大模型精度差强人意，可以将示例插入prompt的[注意]和[用户输入："{user_input}"]之间，但是无法避免LLM直接拿来编
示例：
输入："查询今年的3030连退纯水使用量"
输出：{{"indicator":"3030连退纯水使用量","timeString":"{now.year}","timeType":"YEAR"}}

输入："今天的连退纯水使用量"
输出：{{"indicator":"连退纯水使用量","timeString":"{now.strftime('%Y-%m-%d')}","timeType":"DAY"}}

输入："今天"
输出：{{"indicator":null,"timeString":"{now.strftime('%Y-%m-%d')}","timeType":"DAY"}}

输入："冷轧蒸汽消耗"
输出：{{"indicator":"冷轧蒸汽消耗","timeString":null,"timeType":null}}

输入："8月份冷轧蒸汽消耗"
输出：{{"indicator":"冷轧蒸汽消耗","timeString":"{now.year}-08","timeType":"MONTH"}}

输入："2024年第31周纯水损失率"
输出：{{"indicator":"纯水损失率","timeString":"2024-W31","timeType":"WEEK"}}

输入："2017年第1季度纯水损失率"
输出：{{"indicator":"纯水损失率","timeString":"2017 Q1","timeType":"QUARTER"}}

输入："2019年8月下旬冷轧蒸汽消耗"
输出：{{"indicator":"冷轧蒸汽消耗","timeString":"2019-08 下旬","timeType":"TENDAYS"}}

输入："前天晚班的冷轧蒸汽消耗"
输出：{{"indicator":"冷轧蒸汽消耗","timeString":"{(now - timedelta(days=2)).strftime('%Y-%m-%d')} 晚班","timeType":"SHIFT"}}

输入："下周的吨钢用水量"
输出：{{"indicator":"吨钢用水量","timeString":"{(now + timedelta(weeks=1)).isocalendar()[0]} W{(now + timedelta(weeks=1)).isocalendar()[1]}","timeType":"WEEK"}}

输入："今年10月14日酸轧纯水使用量"
输出：{{"indicator":"酸轧纯水使用量","timeString":"2025-10-14","timeType":"DAY"}}
"""

# ===================== 主解析函数 =====================
async def parse_user_input(user_input: str, now: datetime = None):
    if now is None:
        now = datetime.now()
    now_str = now.strftime("%Y-%m-%d %H:%M")

    prompt = f"""
你是一个智能解析助手，用于从用户输入中提取“指标名称”和“时间信息”。
当前系统时间为：{now_str}。

请严格输出 JSON：
{{
  "indicator": "...",
  "timeString": "...",
  "timeType": "..."
}}

要求：
1. indicator 必须保留原文，包括数字和文字，不要丢失任何信息。
   - 如果数字紧跟在指标词中（如“2030酸轧纯水使用量”、“3030连退纯水使用量”），则视为指标一部分，而非时间。
   - 只有当数字后面带有“年”“月份”“月”“周”“季度”“日”等时间修饰词时，才视为时间。
   - 不要因为指标中包含数字就将其误判为时间。
   - 如果能够明确用户输入就是指明时间点或者时间区间，indicator 就设为null(如“第四周”、“今年三月份”、“2022年5月20日”, “今年一月到五月”, "上半年")。
   - 指标中可能包含描述性质的后缀词（如“累计”、“计划”、“目标”、“完成值”、“用量”、“指标”、“成本”、“效率”、“总量”、“单耗”、“强度”等）。
   - 指标中可能包含“#”“$”(如“1#高炉”、“2#酸轧”等)。
     这些词均属于指标的一部分，必须保留在 indicator 中，不得截断。

2. timeString 必须根据 timeType 精确格式化：
   - HOUR → "YYYY-MM-DD HH"
   - SHIFT → "YYYY-MM-DD 早班/白班/夜班"
     - “早班”、“白班”、“夜班”、“中班”、“晚班” 都属于 SHIFT 类型。
     - 班次优先级高于 HOUR。即如果句中出现“早班/白班/夜班”，无论是否同时出现“几点”，都按 SHIFT 解析。
     - 日期计算规则与 DAY 相同：  
       “昨天早班” → (now - timedelta(days=1)).strftime("%Y-%m-%d") + " 早班"
       “今天白班” → now.strftime("%Y-%m-%d") + " 白班"
       “明天夜班” → (now + timedelta(days=1)).strftime("%Y-%m-%d") + " 夜班"
   - DAY → "YYYY-MM-DD"
     - “去年今天”、“前年昨天” 都属于 DAY 类型，并基于当前时间 {now_str} 推算。
   - WEEK → "YYYY W##"
     - 使用 ISO 标准周号（周一为一周开始）。
     - “本周” 表示当前日期所在周号： now.isocalendar().week
     - “上周” 表示前一周： (now - timedelta(weeks=1)).isocalendar().week
     - “下周” 表示后一周： (now + timedelta(weeks=1)).isocalendar().week
     - 年份应对应该周的 ISO 年份： now.isocalendar().year
   - MONTH → "YYYY-MM"
     - 如果输入中只出现月份（如“8月份”、“9月”），则补上当前年份，例如："2025-08"
     - 如果出现“去年8月份”，则使用去年年份："2024-08"
     - 如果出现“明年3月份”，则使用明年年份："2026-03"
     - 如果出现“上个月”，则使用使用今年年份："2025-09"（假如这个月是2025年10月份）
     - 如果输入中出现“月”后跟“日”，例如“10月14日”，则优先判断为 DAY：
       输出格式：{{"timeString":"YYYY-MM-DD","timeType":"DAY"}}
   - QUARTER → "YYYY Q#"
   - TENDAYS → "YYYY-MM 上旬/中旬/下旬"
   - YEAR → "YYYY"
   若无法推算则为 null。

3. timeType 必须是以下之一：
   ["HOUR","SHIFT","DAY","WEEK","MONTH","QUARTER","TENDAYS","YEAR"]
   若无法判断则为 null。

4. 支持相对时间（今天、昨天、上周、上月、今年、去年等），并基于当前时间 {now_str} 推算。

5. 你还需要支持区间时间表达，例如：
   - "10月1日到10月7日的吨钢蒸汽消耗"
   - "2024-09-01~2024-09-07纯水损失率"
   - "从上周到本周的高炉能耗"
   - "今年1月到3月吨钢用水量"
   在这种情况下：
   - indicator 不变；
   - timeString 统一输出为 "开始时间~结束时间"；
   - timeType 保持最合适的时间粒度（如 DAY、WEEK、MONTH、YEAR）。

此外，还要支持“模糊区间表达”，即未明确出现‘到’、‘至’、‘~’但语义上表示区间的时间短语。
包括但不限于(假设今年是2025年)：
- “一月到三月”、“1月至3月”、“1-3月” → 当年区间 "2025-01~2025-03"
- “去年一月到三月” → 去年区间 "2024-01~2024-03"
- “上半年” → 当年上半年 "2025-01~2025-06"
- “下半年” → 当年下半年 "2025-07~2025-12"
这些模糊区间：
1. 也必须以“开始~结束”输出；
2. timeType 通常为 MONTH；
3. 若出现“去年/明年”，则调整年份。

请严格输出 JSON, 添加多余文字、解释或注释。

注意：
- “indicator” 必须只包含指标名称，不包含时间相关词（如“今年”、“9月份”、“昨天”、“上周”、“第3季度”等）。
- 指标中若包含性质修饰（如“累计”、“计划”、“目标”、“用量”、“成本”、“效率”等），必须保留。
  例如：
  - “本月累计的高炉工序能耗是多少” → indicator="高炉工序能耗累计"
  - “高炉工序能耗本月计划是多少” → indicator="高炉工序能耗计划"
  - “2022年1号高炉工序能耗计划” → indicator="1号高炉工序能耗计划"
  - “1#高炉工序能耗计划” → indicator="1#高炉工序能耗计划"
  - “去年12月吨钢蒸汽成本” → indicator="吨钢蒸汽成本"
  - “明年目标纯水损失率” → indicator="目标纯水损失率"
  - “2022年2月3日” → indicator=null
- 班次词（早班、白班、夜班、中班、晚班）属于时间，不属于指标。
- SHIFT 类型优先于 HOUR：不要将“早班”错误地转化为具体小时。
- 若原文不包含时间或者无法推算出时间，不要私自赋予时间，保持null即可。
- 当出现“本月1号高炉”出现时，优先将“本月”识别为时间，将”1号高炉“解析成指标，而不是将“本月1号”识别成时间。
- 只有明确确认描述的是时间区间才使用区间方式，否则一律使用时间点方式
  例如：
  - “今年累计的”(假设今年是2025年) → indicator=null、timeString="2025"、timeType="YEAR"
  - “上周的”(假设本周是43周) → indicator=null、timeString="2025 W42"、timeType="WEEK"
- 区间是同时识别两个时间，中间用“~”拼接作为timeString，timeType严格执行前面提到的规则
  例如：
  - “一月到三月的吨钢蒸汽消耗”(假设今年是2025年) → indicator="吨钢蒸汽消耗"、timeString="2025-01~2025-03"、timeType="MONTH"
  - “上半年高炉计划”(假设今年是2025年) → indicator="高炉计划"、timeString="2025-01~2025-06"、timeType="MONTH"
  - "2023年上半年" → indicator=null、timeString="2023-01~2023-06"、timeType="MONTH"


用户输入："{user_input}"
"""

    # 调用安全 LLM 函数
    result = await safe_llm_parse(prompt)

    indicator = result.get("indicator")
    timeString = result.get("timeString")
    timeType = result.get("timeType")

    
    if indicator:
        indicator = re.sub(r'^(今天|昨天|明天|本周|上周|下周|上月|本月|今年|去年)\s*的?', '', indicator)
        indicator = re.sub(r'\s*(今天|昨天|明天|本周|上周|下周|上月|本月|今年|去年)$', '', indicator)
        indicator = indicator.strip() or None

    return {"indicator": indicator, "timeString": timeString, "timeType": timeType}


# ===================== 测试 =====================
if __name__ == "__main__":
    import nest_asyncio
    nest_asyncio.apply()
    loop = asyncio.get_event_loop()
    now = datetime(2025, 10, 16, 14, 0)

    test_inputs = [
        "本月1号高炉工序能耗",
        "本月2号高炉工序能耗",
        "1号高炉工序能耗计划",
        "2022年1号高炉工序能耗计划",
        "1号高炉工序能耗"
        "今天是什么日期",
        "2023上半年",
        "2023年上半年",
        "一月到三月的吨钢蒸汽消耗",
        "去年一月到8月吨钢用水量",
        "去年一、二月吨钢用水量",
        "上半年计划",
        "下半年纯水消耗",
        "2024年9月1日到9月7日高炉能耗",
        "今天的连退纯水使用量",
        "2022年10月2日",
        "450酸轧纯水使用量",
        "查询今年的2030酸轧纯水使用量",
        "今天的酸轧纯水使用量",
        "9月份热轧蒸汽消耗",
        "酸轧纯水使用量",
        "昨天",
        "2025年第41周纯水损失率",
        "今年10月14日酸轧纯水使用量",
        "本周",
        "上周的吨钢用水量",
        "昨天早班的热轧蒸汽消耗",
        "明天凌晨2点的轧制水耗",
        "去年12月份的吨钢用水量",
        "2025年第4季度纯水损失率",
        "2025年10月上旬热轧蒸汽消耗",
        "今天的高炉工序能耗是多少",
        "高炉今天的工序能耗是多少",
        "本月累计的高炉工序能耗是多少",
        "1号高炉昨天的工序能耗是多少",
        "去年今天的高炉工序能耗是多少",
        "2021年10月23日的1高炉工序能耗是多少",
        "2023年10月22日的2高炉工序能耗是多少",
        "时间：2021-10-23，1高炉工序能耗是多少",
        "高炉工序能耗是多少",
        "本月1、2号高炉工序能耗是多少",
        "高炉工序能耗本月计划是多少",
        "本月高炉工序能耗的计划值是多少",
        "本月的高炉电耗是多少",
        "本月的高炉电使用量是多少",
        "高炉的煤气耗是多少",
        "10号高炉今天的工序能耗是多少",
        "今年累计的冷轧蒸汽消耗是多少",
        "前天晚班的吨钢用水量"
    ]

    for ti in test_inputs:
        result = loop.run_until_complete(parse_user_input(ti))
        print(f"{ti} => {result}")
