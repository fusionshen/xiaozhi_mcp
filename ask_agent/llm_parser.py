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
当前系统时间为：{now_str}。

请严格输出 JSON：
{{
  "indicator": "...",
  "timeString": "...",
  "timeType": "..."
}}

要求：
1. indicator 必须保留原文，包括数字和文字，不要丢失任何信息。
2. timeString 根据 timeType 格式化：
   - HOUR → "YYYY-MM-DD HH"
   - SHIFT → "YYYY-MM-DD 早班/白班/夜班"
   - DAY → "YYYY-MM-DD"
   - WEEK → "YYYY-W##"
   - MONTH → "YYYY-MM"
   - QUARTER → "YYYY Q#"
   - TENDAYS → "YYYY-MM 上旬/中旬/下旬"
   - YEAR → "YYYY"
   - 若无法推算则为 null
3. timeType 取值 ["HOUR","SHIFT","DAY","WEEK","MONTH","QUARTER","TENDAYS","YEAR"]，若无法判断为 null
4. 只解析输入中真正的指标和时间，不要添加无关字符。
5. 当前时间为参考，用户可能输入相对时间（今天、昨天、上周、本周、本月、上月、今年、去年、上旬、中旬、下旬、季度等）。
6. 指标中出现的时间词不要去掉数字和专有名词。

示例：
输入："查询今年的3030连退纯水使用量"
输出：{{"indicator":"3030连退纯水使用量","timeString":"{now.year}","timeType":"YEAR"}}

输入："今天的连退纯水使用量"
输出：{{"indicator":"连退纯水使用量","timeString":"{now.strftime('%Y-%m-%d')}","timeType":"DAY"}}

输入："今天"
输出：{{"indicator":None,"timeString":"{now.strftime('%Y-%m-%d')}","timeType":"DAY"}}

输入："冷轧蒸汽消耗"
输出：{{"indicator":"冷轧蒸汽消耗","timeString":None,"timeType":None}}

输入："8月份冷轧蒸汽消耗"
输出：{{"indicator":"冷轧蒸汽消耗","timeString":"{now.strftime('%Y-%m')}","timeType":"MONTH"}}

输入："2024年第31周纯水损失率"
输出：{{"indicator":"纯水损失率","timeString":"2024-W31","timeType":"WEEK"}}

输入："2017年第1季度纯水损失率"
输出：{{"indicator":"纯水损失率","timeString":"2017 14","timeType":"QUARTER"}}

输入："2019年8月下旬冷轧蒸汽消耗"
输出：{{"indicator":"冷轧蒸汽消耗","timeString":"2019-08 下旬","timeType":"TENDAYS"}}

输入："前天晚班的冷轧蒸汽消耗"
输出：{{"indicator":"冷轧蒸汽消耗","timeString":"{(now - timedelta(days=2)).strftime('%Y-%m-%d')} 晚班","timeType":"SHIFT"}}

输入："下周的吨钢用水量"
输出：{{"indicator":"吨钢用水量","timeString":"{(now + timedelta(weeks=1)).isocalendar()[0]}-W{(now + timedelta(weeks=1)).isocalendar()[1]}","timeType":"WEEK"}}

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

    # ===================== 时间格式兜底修正 =====================
    timeString = result.get("timeString")
    timeType = result.get("timeType")
    indicator = result.get("indicator")

    if timeString and timeType:
        # WEEK 格式修正
        if timeType == "WEEK":
            m = re.match(r'(\d{4})\D*(\d{1,2})', timeString)
            if m:
                timeString = f"{m.group(1)}-W{int(m.group(2)):02d}"
        # QUARTER 格式修正
        elif timeType == "QUARTER":
            m = re.match(r'(\d{4})\D*(\d)', timeString)
            if m:
                timeString = f"{m.group(1)} Q{m.group(2)}"
        # TENDAYS 上中下旬
        elif timeType == "TENDAYS":
            m = re.match(r'(\d{4}-\d{2}).*?(上旬|中旬|下旬)', timeString)
            if m:
                timeString = f"{m.group(1)} {m.group(2)}"
        # SHIFT 格式修正
        elif timeType == "SHIFT":
            m = re.match(r'(\d{4}-\d{2}-\d{2}).*?(早班|白班|夜班)', timeString)
            if m:
                timeString = f"{m.group(1)} {m.group(2)}"
        # HOUR
        elif timeType == "HOUR":
            m = re.match(r'(\d{4}-\d{2}-\d{2})\D*(\d{1,2})', timeString)
            if m:
                timeString = f"{m.group(1)} {int(m.group(2)):02d}"
        # MONTH、DAY、YEAR 保持 YYYY-MM / YYYY-MM-DD / YYYY
        elif timeType in ["MONTH", "DAY", "YEAR"]:
            m = re.match(r'(\d{4}-\d{2}-\d{2}|\d{4}-\d{2}|\d{4})', timeString)
            if m:
                timeString = m.group(1)

    # ===================== 指标清理 =====================
    if indicator:
        # 去掉前后时间词，但保留数字和专有名词
        indicator = re.sub(r'^(今天|昨天|明天|本周|上周|本周|上月|本月|今年|去年)\s*的?', '', indicator)
        indicator = re.sub(r'\s*(今天|昨天|明天|本周|上周|本周|上月|本月|今年|去年)$', '', indicator)
        indicator = indicator.strip()
        if not indicator:
            indicator = None

    return {"indicator": indicator, "timeString": timeString, "timeType": timeType}

# ===================== 测试 =====================
if __name__ == "__main__":
    import nest_asyncio
    nest_asyncio.apply()
    loop = asyncio.get_event_loop()
    now = datetime(2025, 10, 15, 14, 0)

    test_inputs = [
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
        "2025年10月上旬热轧蒸汽消耗"
    ]

    for ti in test_inputs:
        result = loop.run_until_complete(parse_user_input(ti, now))
        print(f"{ti} => {result}")
