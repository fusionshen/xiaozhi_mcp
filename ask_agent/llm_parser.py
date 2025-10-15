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
    使用 LLM 提取指标和时间信息，并做轻量兜底标准化
    """
    if now is None:
        now = datetime.now()
    now_str = now.strftime("%Y-%m-%d %H:%M")

    prompt = f"""
你是智能指标解析助手，用于从用户输入中提取指标和时间信息。
当前时间：{now_str}。请解析用户输入中的相对或绝对时间。

要求：
1. 尽量保留指标完整性（除了明确时间信息之外）。
2. 尝试解析时间，包括天、周、月、年、季度、旬、班次、小时。
3. 输出严格 JSON 格式：
{{
  "indicator": "...",
  "timeString": "...",
  "timeType": "..."
}}
字段说明：
- indicator：指标名称，若无可识别指标填 null
- timeString：标准化时间，格式：
    HOUR → YYYY-MM-DD HH
    SHIFT → YYYY-MM-DD 早班/白班/夜班
    DAY → YYYY-MM-DD
    WEEK → YYYY-W##
    MONTH → YYYY-MM
    QUARTER → YYYY Q#
    TENDAYS → YYYY-MM 上旬/中旬/下旬
    YEAR → YYYY
    若无法推算填 null
- timeType：取值 ["HOUR","SHIFT","DAY","WEEK","MONTH","YEAR","QUARTER","TENDAYS"]，无法判断可填 null

示例：
输入："查询今年的2030酸轧纯水使用量"
输出：{{"indicator":"2030酸轧纯水使用量","timeString":"{now.year}","timeType":"YEAR"}}

输入："今天的酸轧纯水使用量"
输出：{{"indicator":"酸轧纯水使用量","timeString":"{now.strftime('%Y-%m-%d')}","timeType":"DAY"}}

输入："9月份热轧蒸汽消耗"
输出：{{"indicator":"热轧蒸汽消耗","timeString":"{now.strftime('%Y-%m')}","timeType":"MONTH"}}

输入："2025年第41周纯水损失率"
输出：{{"indicator":"纯水损失率","timeString":"2025-W41","timeType":"WEEK"}}

输入："2025年第4季度纯水损失率"
输出：{{"indicator":"纯水损失率","timeString":"2025 Q4","timeType":"QUARTER"}}

输入："2025年10月上旬热轧蒸汽消耗"
输出：{{"indicator":"热轧蒸汽消耗","timeString":"2025-10 上旬","timeType":"TENDAYS"}}

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

    # ===================== 轻量兜底标准化 =====================
    indicator = result.get("indicator")
    timeString = result.get("timeString")
    timeType = result.get("timeType")

    # timeType None 时尝试从 timeString 推算
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
        elif re.match(r'^\d{4}\s*Q\d$', timeString):
            timeType = "QUARTER"
        elif re.match(r'^\d{4}-\d{2}\s*(上旬|中旬|下旬)$', timeString):
            timeType = "TENDAYS"
        elif re.match(r'^\d{4}$', timeString):
            timeType = "YEAR"

    # 若时间缺失，timeType 与 timeString 都为 None
    if not timeString:
        timeType = None

    # 去掉 indicator 前后残留的时间词
    if indicator:
        indicator = re.sub(r'^(今天|昨天|明天|本周|上周|本周|本月|上月|今年|去年|第\d季度)\s*的?', '', indicator)
        indicator = re.sub(r'\s*(今天|昨天|明天|本周|上周|本月|上月|今年|去年|第\d季度)$', '', indicator)
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
