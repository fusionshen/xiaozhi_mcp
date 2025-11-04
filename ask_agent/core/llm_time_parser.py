import re
import asyncio
from datetime import datetime, timedelta, date
from core.llm_client import safe_llm_parse

"""
llm_time_parser: 智能日期/时间问答解析器
支持问答包括：
- 当前时间/日期/星期
- 第几周、第几季度
- 上周、下个月、去年等相对时间
- 任意日期对应星期几
- 周的起止日期、季度起止月份
"""

async def parse_time_question(user_input: str, now: datetime = None):
    if now is None:
        now = datetime.now()

    now_str = now.strftime("%Y-%m-%d %H:%M:%S")

    prompt = f"""
你是一个智能时间解析助手。
当前系统时间是 {now_str}。

任务：
理解用户问题并计算出对应的时间结果。支持的问题类型包括：
1. 当前时间 / 日期 / 星期（例如“现在几点了”“今天几号”“今天星期几”）
2. 周信息（例如“今年第几周”“下周一是几号”“2025年第13周是哪天开始”）
3. 月份信息（例如“这个月有几天”“去年十月份是哪天开始”）
4. 季度信息（例如“现在是第几季度”“去年第四季度是哪几个月”）
5. 年份、半年（例如“现在是上半年还是下半年”“明年是哪一年”）
6. 节日（例如“今年国庆节是星期几”“2026年春节是哪天”）

输出严格为 JSON：
{{
  "intent": "TIME_QUERY",
  "question": "用户原始问题",
  "answer": "自然语言回答",
  "detail": {{
    "type": "WEEK|DAY|MONTH|QUARTER|YEAR|SHIFT|HOLIDAY",
    "start_date": "如为区间则给出起始日期",
    "end_date": "如为区间则给出结束日期",
    "extra": "可选补充说明，如星期、天数、季度号等"
  }}
}}

注意：
- answer 必须是自然语言可直接回复的句子。
- 不要解释计算步骤。
- 不要添加多余文字或说明。
- 对于无法判断的问题，answer 设为 "暂无法解析该时间问题"。
- 对节日问题（如国庆、春节），仅输出阳历日期。
- 若需要日期计算，请基于 {now_str}。

用户输入: "{user_input}"
"""

    result = await safe_llm_parse(prompt)

    # 防御式兜底
    if not isinstance(result, dict):
        return {
            "intent": "TIME_QUERY",
            "question": user_input,
            "answer": "暂无法解析该时间问题。",
            "detail": {"type": None}
        }

    return result


# ===================== 测试 =====================
if __name__ == "__main__":
    import nest_asyncio
    nest_asyncio.apply()
    loop = asyncio.get_event_loop()

    test_inputs = [
        "现在几点了",
        "今天是星期几",
        "今年第几周",
        "上周一是几号",
        "下周五的日期",
        "今年第3季度是哪几个月",
        "去年下半年是哪几个月",
        "2025年第13周是哪天开始",
        "国庆节是星期几",
        "春节是哪天",
        "2026年春节是哪天",
        "上个月有几天",
    ]

    now = datetime(2025, 10, 29, 9, 0)
    for q in test_inputs:
        res = loop.run_until_complete(parse_time_question(q, now))
        print(f"❓ {q}\n➡️ {res['answer']}\n")
