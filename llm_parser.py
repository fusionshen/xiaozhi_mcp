import asyncio
import re
import json

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

# ===================== 时间关键词 =====================
TIME_KEYWORDS = [
    "今天", "昨天", "本周", "上周", "本月", "上月", "今年", "去年"
]
TIME_REGEX = [
    r"\d{4}年\d{1,2}月\d{1,2}日",
    r"\d{4}年\d{1,2}月",
    r"\d{1,2}月份",
    r"\d{4}年",
    r"\d{4}年第\d季度",
    r"\d季度"
]

# ===================== 解析函数 =====================
async def parse_user_input(user_input: str):
    """
    使用 Ollama 模型从用户输入中提取：
    - indicator（指标名称）
    - date（时间信息）
    """
    prompt = f"""
你是一个解析助手，负责从用户的自然语言中提取查询指标名称（indicator）和时间信息（date）。
请严格按照以下规则输出：

1. 用户输入可能包含时间和指标名称。
   - 时间表达示例：今天、昨天、本月、上月、上周、2025年10月、9月份、2024年第一季度等。
   - 指标名称示例：酸轧纯水使用量、热轧蒸汽消耗、纯水损失率、吨钢用水量等。

2. 输出 JSON 格式，字段为：
{"{"}"indicator": "...", "date": "..."{"}"} 

3. 如果时间信息未提及，请将 "date" 设为 null；
   如果指标名称未提及，请将 "indicator" 设为 null。

4. 只输出 JSON，不要解释说明或添加任何额外文本。

示例：
用户输入："今天的酸轧纯水使用量"
输出：{{"indicator":"酸轧纯水使用量","date":"今天"}}

用户输入："9月份热轧蒸汽消耗"
输出：{{"indicator":"热轧蒸汽消耗","date":"9月份"}}

用户输入："酸轧纯水使用量"
输出：{{"indicator":"酸轧纯水使用量","date":null}}

用户输入："昨天"
输出：{{"indicator":null,"date":"昨天"}}

用户输入："{user_input}"
"""
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
        # 尝试正则提取 indicator 和 date
        indicator_match = re.search(r'"indicator"\s*:\s*"([^"]*)"', content)
        date_match = re.search(r'"date"\s*:\s*"([^"]*)"', content)
        result = {
            "indicator": indicator_match.group(1) if indicator_match else None,
            "date": date_match.group(1) if date_match else None
        }

    # ===================== 容错：date =====================
    date_found = None
    # 优先匹配显式时间关键词
    for kw in TIME_KEYWORDS:
        if kw in user_input:
            date_found = kw
            break
    # 如果没有显式关键词，再匹配正则
    if not date_found:
        for regex in TIME_REGEX:
            match = re.search(regex, user_input)
            if match:
                date_found = match.group(0)
                break
    result["date"] = date_found

    # ===================== 容错：indicator =====================
    if not result.get("indicator"):
        # 去掉时间信息后的剩余文本作为 indicator
        tmp = user_input
        if date_found:
            tmp = tmp.replace(date_found, "")
        # 去掉一些无意义的助词
        tmp = re.sub(r"的|查询|请|显示|给我|帮我", "", tmp).strip()
        result["indicator"] = tmp if tmp else None
    else:
        # 进一步优化：保留数字+指标组合，如 "2030酸轧纯水使用量"
        if result["indicator"] not in user_input:
            # 尝试匹配包含数字的指标
            match = re.search(r"(\d+.*?(" + re.escape(result["indicator"]) + r"))", user_input)
            if match:
                result["indicator"] = match.group(1)

    return result

# ===================== 测试 =====================
if __name__ == "__main__":
    test_inputs = [
        "查询今年的2030酸轧纯水使用量",
        "今天的酸轧纯水使用量",
        "9月份热轧蒸汽消耗",
        "酸轧纯水使用量",
        "昨天",
        "2030酸轧纯水使用量"
    ]
    # asyncio 兼容处理
    import nest_asyncio
    nest_asyncio.apply()
    loop = asyncio.get_event_loop()

    for ti in test_inputs:
        result = loop.run_until_complete(parse_user_input(ti))
        print(f"{ti} => {result}")
