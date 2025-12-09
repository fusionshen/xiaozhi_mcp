import logging
from core.llm.llm_client import safe_llm_chat

logger = logging.getLogger("llm.indicator.compare")
if not logger.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )


def build_compare_prompt(a: str, b: str) -> str:
    """
    统一构造对比提示词：
    - 自动从 indicators 提取：indicator 名称、时间、value、note
    - 允许两个 indicator 名称不同（比如 1高炉 vs 高炉）
    - 自动判断 None / 缺失
    """
    # 提取 A
    name_a = a.get("indicator", "")
    time_a = a.get("timeString", "")
    type_a = a.get("timeType", "")
    value_a = a.get("value", None)
    note_a = a.get("note", "")

    # 提取 B
    name_b = b.get("indicator", "")
    time_b = b.get("timeString", "")
    type_b = b.get("timeType", "")
    value_b = b.get("value", None)
    note_b = b.get("note", "")
    return f"""
你是能源分析助手。下面是两条查询结果（可能包含 None 表示无数据）。
请根据以下两条结果，生成一句自然语言的对比结论，要求：

👉 绝对禁止使用“结果A / 结果B / 第一个 / 第二个”等指代  
👉 必须直接引用指标名称（如：1高炉工序能耗实绩报出值）  
👉 指出差值方向（更高/更低/相差多少）  
👉 若任意一个值为 None 或空，需说明无法计算  
👉 语言自然、简洁、符合中文表达习惯  

以下是两条原始结果：

① {name_a} 在 {time_a}({type_a}) 的值是：{value_a}  
原始Note：{note_a}

② {name_b} 在 {time_b}({type_b}) 的值是：{value_b}  
原始Note：{note_b}

请直接生成一句中文对比结论，不要客套，不要解释原理。
"""


async def call_compare_llm(a: dict, b: dict) -> str:
    """
    统一对比 LLM 调用。
    返回一句对比结论（已经容错处理）
    """
    prompt = build_compare_prompt(a, b)

    try:
        result = await safe_llm_chat(prompt)
        if result:
            result = result.strip()
            logger.info(f"🔍 compare LLM 输出: {result}")
            return result
    except Exception as e:
        logger.exception("❌ compare LLM 调用失败: %s", e)

    # fallback：不让 compare 阶段报错
    return f"对比结果：A={a.get("note", "")}; B={b.get("note", "")}"
