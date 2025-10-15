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
    使用 LLM 提取指标与时间。
    now: 当前系统时间，用于解释“今天”“昨天”等相对时间。
    """
    if now is None:
        now = datetime.now()
    now_str = now.strftime("%Y-%m-%d %H:%M")

    prompt = f"""
你是一个智能解析助手，用于从用户输入中提取“指标名称”和“时间信息”。
系统当前时间是：{now_str}。请基于这个时间推算“今天”“昨天”“上周”等相对时间。

请严格输出以下 JSON 结构：
{{
  "indicator": "...",
  "timeString": "...",
  "timeType": "..."
}}

### 字段定义：
1. **indicator**：指标名称（如“酸轧纯水使用量”、“热轧蒸汽消耗”等），若无则 null。
2. **timeString**：标准化时间表示（根据 timeType 决定格式）：
   - HOUR → “2025-10-14 02”
   - SHIFT → “2025-10-14 2白” 或 “2025-10-14 2夜”
   - WEEK → “2025 W41”
   - DAY → “2025-10-14”
   - MONTH → “2025-10”
   - YEAR → “2025”
   - 若无时间信息则为 null。
3. **timeType**：时间粒度类型，取值之一：
   ["HOUR", "SHIFT", "WEEK", "DAY", "MONTH", "YEAR"]

### 时间理解规则：
- 现在时间是 {now_str}
- “今天” → {now.strftime("%Y-%m-%d")}
- “昨天” → {(now - timedelta(days=1)).strftime("%Y-%m-%d")}
- “前天” → {(now - timedelta(days=2)).strftime("%Y-%m-%d")}
- “上周” → 上一自然周，例如 “2025 W{(now.isocalendar().week - 1)}”
- “本周” → 当前自然周 “2025 W{now.isocalendar().week}”
- “本月” → {now.strftime("%Y-%m")}
- “上月” → { (now.replace(day=1) - timedelta(days=1)).strftime("%Y-%m") }
- “今年” → {now.strftime("%Y")}
- “去年” → {now.year - 1}

### 示例：
输入："查询今年的2030酸轧纯水使用量"
输出：{{"indicator":"2030酸轧纯水使用量","timeString":"{now.strftime('%Y')}","timeType":"YEAR"}}

输入："今天的酸轧纯水使用量"
输出：{{"indicator":"酸轧纯水使用量","timeString":"{now.strftime('%Y-%m-%d')}","timeType":"DAY"}}

输入："9月份热轧蒸汽消耗"
输出：{{"indicator":"热轧蒸汽消耗","timeString":"2025-09","timeType":"MONTH"}}

输入："昨天"
输出：{{"indicator":null,"timeString":"{(now - timedelta(days=1)).strftime('%Y-%m-%d')}","timeType":"DAY"}}

输入："2025年第41周纯水损失率"
输出：{{"indicator":"纯水损失率","timeString":"2025 W41","timeType":"WEEK"}}

用户输入："{user_input}"
"""

    try:
        resp = await llm.agenerate([[HumanMessage(content=prompt)]])
        content = resp.generations[0][0].message.content.strip()
    except Exception as e:
        print("❌ LLM 调用失败:", e)
        content = ""

    # ========== JSON 容错解析 ==========
    try:
        result = json.loads(content)
    except json.JSONDecodeError:
        indicator_match = re.search(r'"indicator"\s*:\s*"([^"]*)"', content)
        timeString_match = re.search(r'"timeString"\s*:\s*"([^"]*)"', content)
        timeType_match = re.search(r'"timeType"\s*:\s*"([^"]*)"', content)
        result = {
            "indicator": indicator_match.group(1) if indicator_match else None,
            "timeString": timeString_match.group(1) if timeString_match else None,
            "timeType": timeType_match.group(1) if timeType_match else None
        }

    # ========== 容错兜底 ==========
    if not result.get("timeType"):
        text = user_input
        if any(kw in text for kw in ["小时", "点", "时"]):
            result["timeType"] = "HOUR"
        elif any(kw in text for kw in ["白", "夜"]):
            result["timeType"] = "SHIFT"
        elif any(kw in text for kw in ["周", "星期"]):
            result["timeType"] = "WEEK"
        elif any(kw in text for kw in ["月", "月份"]):
            result["timeType"] = "MONTH"
        elif any(kw in text for kw in ["年"]):
            result["timeType"] = "YEAR"
        else:
            result["timeType"] = "DAY"

    return result


# ===================== 测试 =====================
if __name__ == "__main__":
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
    import nest_asyncio
    nest_asyncio.apply()
    loop = asyncio.get_event_loop()
    now = datetime(2025, 10, 15, 14, 0)  # 模拟当前时间

    for ti in test_inputs:
        result = loop.run_until_complete(parse_user_input(ti, now))
        print(f"{ti} => {result}")
