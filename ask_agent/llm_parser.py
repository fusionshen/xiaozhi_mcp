import asyncio
import re
import json
from datetime import datetime, timedelta

# ===================== ChatOllama 兼容导入 =====================
try:
    from langchain_ollama import ChatOllama
    print("✅ Using ChatOllama from langchain-ollama")
except ImportError:
    try:
        from langchain_community.chat_models import ChatOllama
        print("✅ Using ChatOllama from langchain_community")
    except ImportError:
        from langchain.chat_models import ChatOllama
        print("⚠️ Using ChatOllama from old langchain (may be deprecated)")

from langchain.schema import HumanMessage

# ===================== 初始化 LLM =====================
llm = ChatOllama(model="qwen2.5:1.5b")

# ===================== 主解析函数 =====================
async def parse_user_input(user_input: str, now: datetime = None):
    """
    使用 LLM 提取指标和时间信息。
    now: 当前系统时间，用于解析“今天”“昨天”等相对时间。
    """
    if now is None:
        now = datetime.now()
    now_str = now.strftime("%Y-%m-%d %H:%M")

    prompt = f"""
你是一个智能解析助手，用于从用户输入中提取“指标名称”和“时间信息”。
当前系统时间为：{now_str}。请基于此时间推算用户表达的相对时间（如“今天”“昨天”“上周”“今年10月14日”等）。

请严格输出 JSON：
{{
  "indicator": "...",
  "timeString": "...",
  "timeType": "..."
}}

字段说明：
- indicator：指标名称（如“酸轧纯水使用量”、“热轧蒸汽消耗”），若无则为 null
- timeString：时间标准化字符串，根据 timeType 定义：
    - HOUR → "YYYY-MM-DD HH"
    - SHIFT → "YYYY-MM-DD 早班/白班/夜班"
    - DAY → "YYYY-MM-DD"
    - WEEK → "YYYY W##"
    - MONTH → "YYYY-MM"
    - YEAR → "YYYY"
    - 若无法推算则为 null
- timeType：时间粒度类型，取值 ["HOUR", "SHIFT", "DAY", "WEEK", "MONTH", "YEAR"]，若无法判断为 null

示例：
输入："查询今年的2030酸轧纯水使用量"
输出：{{"indicator":"2030酸轧纯水使用量","timeString":"{now.year}","timeType":"YEAR"}}

输入："今天的酸轧纯水使用量"
输出：{{"indicator":"酸轧纯水使用量","timeString":"{now.strftime('%Y-%m-%d')}","timeType":"DAY"}}

输入："9月份热轧蒸汽消耗"
输出：{{"indicator":"热轧蒸汽消耗","timeString":"{now.strftime('%Y-%m')}","timeType":"MONTH"}}

输入："昨天早班的热轧蒸汽消耗"
输出：{{"indicator":"热轧蒸汽消耗","timeString":"{(now - timedelta(days=1)).strftime('%Y-%m-%d')} 早班","timeType":"SHIFT"}}

用户输入："{user_input}"
"""

    # ===================== 调用 LLM =====================
    try:
        resp = await llm.agenerate([[HumanMessage(content=prompt)]])
        content = resp.generations[0][0].message.content.strip()
    except Exception as e:
        print("❌ LLM 调用失败:", e)
        content = ""

    # ===================== JSON 解析 =====================
    try:
        result = json.loads(content)
    except json.JSONDecodeError:
        # 容错解析
        indicator_match = re.search(r'"indicator"\s*:\s*"([^"]*)"', content)
        timeString_match = re.search(r'"timeString"\s*:\s*"([^"]*)"', content)
        timeType_match = re.search(r'"timeType"\s*:\s*"([^"]*)"', content)
        result = {
            "indicator": indicator_match.group(1) if indicator_match else None,
            "timeString": timeString_match.group(1) if timeString_match else None,
            "timeType": timeType_match.group(1) if timeType_match else None
        }

    # ===================== 轻量兜底逻辑 =====================
    indicator = result.get("indicator")
    timeString = result.get("timeString")
    timeType = result.get("timeType")

    # timeType 为 None 时根据自然语言尝试补全
    if not timeType and timeString:
        if re.match(r'^\d{4}-\d{2}-\d{2}\s*\d{2}$', timeString):
            timeType = "HOUR"
        elif re.match(r'^\d{4}-\d{2}-\d{2}\s*(早班|白班|夜班)$', timeString):
            timeType = "SHIFT"
        elif re.match(r'^\d{4}-\d{2}-\d{2}$', timeString):
            timeType = "DAY"
        elif re.match(r'^\d{4}\s*W\d{1,2}$', timeString):
            timeType = "WEEK"
        elif re.match(r'^\d{4}-\d{2}$', timeString):
            timeType = "MONTH"
        elif re.match(r'^\d{4}$', timeString):
            timeType = "YEAR"

    # 若时间缺失，timeType 与 timeString 都为 None
    if not timeString:
        timeType = None

    # 去掉 indicator 前后残留的时间词
    if indicator:
        indicator = re.sub(r'^(今天|昨天|明天|本周|上周|本月|上月|今年|去年)\s*的?', '', indicator)
        indicator = re.sub(r'\s*(今天|昨天|明天|本周|上周|本月|上月|今年|去年)$', '', indicator)
        indicator = indicator.strip()
        if not indicator:
            indicator = None

    return {"indicator": indicator, "timeString": timeString, "timeType": timeType}


# ===================== 测试 =====================
if __name__ == "__main__":
    import nest_asyncio
    nest_asyncio.apply()
    loop = asyncio.get_event_loop()
    now = datetime(2025, 10, 15, 14, 0)  # 模拟当前时间

    test_inputs = [
        "查询今年的2030酸轧纯水使用量",
        "今天的酸轧纯水使用量",
        "9月份热轧蒸汽消耗",
        "酸轧纯水使用量",
        "昨天",
        "2025年第41周纯水损失率",
        "今年10月14日酸轧纯水使用量",
        "上周的吨钢用水量",
        "昨天早班的热轧蒸汽消耗",
        "明天凌晨2点的轧制水耗",
        "去年12月份的吨钢用水量"
    ]

    for ti in test_inputs:
        result = loop.run_until_complete(parse_user_input(ti, now))
        print(f"{ti} => {result}")
