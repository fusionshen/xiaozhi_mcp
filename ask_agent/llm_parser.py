# llm_parser.py
import asyncio
from langchain.chat_models import ChatOllama
from langchain.schema import HumanMessage
import re

# 初始化本地 Ollama 模型
llm = ChatOllama(model="qwen2.5:1.5b")

async def parse_user_input(user_input: str):
    """
    使用 Ollama 模型从用户输入中提取：
    - indicator（指标名称）
    - date（时间信息）
    """
    prompt = f"""
你是一个智能解析助手。请从用户输入中提取两个信息：
1. 指标名称（indicator）：用户要查询的核心指标，例如“酸轧纯水使用量”，去掉“的”等无意义助词。
2. 时间（date）：用户提到的时间信息，例如“今天”“昨天”“2025-10-13”，如果未提及，请输出 null。

用户输入："{user_input}"

输出要求：
- 必须只输出 JSON
- JSON 格式：{{"indicator": "...", "date": "..."}}
- 未提及的字段用 null
- 不要额外文本
"""
    # 调用 Ollama
    resp = await llm.agenerate([[HumanMessage(content=prompt)]])
    content = resp.generations[0][0].message.content

    # 简单容错处理，尽量提取 JSON
    try:
        import json
        return json.loads(content)
    except:
        # 尝试正则提取 "indicator" 和 "date"
        indicator_match = re.search(r'"indicator"\s*:\s*"([^"]*)"', content)
        date_match = re.search(r'"date"\s*:\s*"([^"]*)"', content)
        return {
            "indicator": indicator_match.group(1) if indicator_match else None,
            "date": date_match.group(1) if date_match else None
        }

# 测试用例
if __name__ == "__main__":
    import asyncio
    test_input = "今天的酸轧纯水使用量"
    result = asyncio.run(parse_user_input(test_input))
    print(result)
