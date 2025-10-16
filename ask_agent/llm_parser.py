import asyncio
import re
import json
import httpx
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

# ===================== 模型优先级定义 =====================
REMOTE_OLLAMA_URL = "http://192.168.92.13:11434"  # ← 修改为你的远程 Ollama 地址
REMOTE_MODEL = "gemma3:27b"
LOCAL_MODEL = "qwen2.5:1.5b"


async def is_remote_ollama_available(base_url: str, timeout: float = 3.0) -> bool:
    """
    检查远程 Ollama 服务是否可访问。
    """
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(f"{base_url}/api/tags")
            if resp.status_code == 200:
                #print(f"🌐 Remote Ollama available at {base_url}")
                return True
    except Exception as e:
        print(f"⚠️ Remote Ollama not reachable: {e}")
    return False


async def get_llm() -> ChatOllama:
    """
    优先使用远程 gemma3:27b，如果远程不可用则回退到本地 qwen2.5:1.5b。
    """
    if await is_remote_ollama_available(REMOTE_OLLAMA_URL):
        #print(f"✅ Using remote model: {REMOTE_MODEL}")
        return ChatOllama(model=REMOTE_MODEL, base_url=REMOTE_OLLAMA_URL)
    else:
        print(f"🔄 Falling back to local model: {LOCAL_MODEL}")
        return ChatOllama(model=LOCAL_MODEL)


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

2. timeString 必须根据 timeType 精确格式化：
   - HOUR → "YYYY-MM-DD HH"
   - SHIFT → "YYYY-MM-DD 早班/白班/夜班"
   - DAY → "YYYY-MM-DD"
   - WEEK → "YYYY-W##"
     - 使用 ISO 标准周号（周一为一周开始）。
     - “本周” 表示当前日期所在周号： now.isocalendar().week
     - “上周” 表示前一周： (now - timedelta(weeks=1)).isocalendar().week
     - “下周” 表示后一周： (now + timedelta(weeks=1)).isocalendar().week
     - 年份应对应该周的 ISO 年份： now.isocalendar().year
   - MONTH → "YYYY-MM"
     - 如果输入中只出现月份（如“8月份”、“9月”），则补上当前年份，例如："2025-08"
     - 如果出现“去年8月份”，则使用去年年份："2024-08"
     - 如果出现“明年3月份”，则使用明年年份："2026-03"
     - 如果输入中出现“月”后跟“日”，例如“10月14日”，则优先判断为 DAY：
       输出格式：{{"timeString":"YYYY-MM-DD","timeType":"DAY"}}
   - QUARTER → "YYYY Q#"
   - TENDAYS → "YYYY-MM 上旬/中旬/下旬"
   - YEAR → "YYYY"
   - 若无法推算则为 null

3. timeType 取值必须为以下之一：
   ["HOUR","SHIFT","DAY","WEEK","MONTH","QUARTER","TENDAYS","YEAR"]
   若无法判断则为 null。

4. 只解析输入中真正的指标和时间，不要添加无关字符。
   - 如果出现“今天”、“昨天”、“明天”、“上周”、“本周”、“下周”、“上月”、“本月”、“今年”、“去年”等相对时间，
     请基于当前时间 {now_str} 推算出精确日期。
   - 指标中的时间词不要删除或修改指标内部数字。

5. 输出格式必须严格为 JSON，不要添加多余文字、解释或注释。

注意：
- “indicator” 必须只包含指标名称，不包含时间相关词（如“今年”、“9月份”、“昨天”、“上周”、“第3季度”等）。
- 例如，“十月份热轧蒸汽消耗”应解析为 indicator="热轧蒸汽消耗"，timeString="2025-10"，timeType="MONTH"。


用户输入："{user_input}"
"""

    llm = await get_llm()

    try:
        resp = await llm.agenerate([[HumanMessage(content=prompt)]])
        content = resp.generations[0][0].message.content.strip()
    except Exception as e:
        print("❌ LLM 调用失败:", e)
        return {"indicator": None, "timeString": None, "timeType": None}

    try:
        result = json.loads(content)
    except json.JSONDecodeError:
        result = {
            "indicator": re.search(r'"indicator"\s*:\s*"([^"]*)"', content).group(1) if re.search(r'"indicator"\s*:\s*"([^"]*)"', content) else None,
            "timeString": re.search(r'"timeString"\s*:\s*"([^"]*)"', content).group(1) if re.search(r'"timeString"\s*:\s*"([^"]*)"', content) else None,
            "timeType": re.search(r'"timeType"\s*:\s*"([^"]*)"', content).group(1) if re.search(r'"timeType"\s*:\s*"([^"]*)"', content) else None
        }

    indicator = result.get("indicator")
    timeString = result.get("timeString")
    timeType = result.get("timeType")

    # ✅ 兜底 WEEK 精确修正
    # ✅ 精准 WEEK 修正（仅处理语义性“上周、本周、下周”）
    if timeType == "WEEK":
        # 仅当出现相对时间词时修正
        if any(word in user_input for word in ["上周", "本周", "下周"]):
            if "上周" in user_input:
                ref = now - timedelta(weeks=1)
            elif "下周" in user_input:
                ref = now + timedelta(weeks=1)
            else:
                ref = now
            iso_year, iso_week, _ = ref.isocalendar()
            timeString = f"{iso_year}-W{iso_week:02d}"


    # ✅ 格式修正逻辑保留
    if timeString and timeType:
        if timeType == "WEEK":
            m = re.match(r'(\d{4})\D*(\d{1,2})', timeString)
            if m:
                timeString = f"{m.group(1)}-W{int(m.group(2)):02d}"
        elif timeType == "QUARTER":
            m = re.match(r'(\d{4})\D*(\d)', timeString)
            if m:
                timeString = f"{m.group(1)} Q{m.group(2)}"
        elif timeType == "TENDAYS":
            m = re.match(r'(\d{4}-\d{2}).*?(上旬|中旬|下旬)', timeString)
            if m:
                timeString = f"{m.group(1)} {m.group(2)}"
        elif timeType == "SHIFT":
            m = re.match(r'(\d{4}-\d{2}-\d{2}).*?(早班|白班|夜班)', timeString)
            if m:
                timeString = f"{m.group(1)} {m.group(2)}"
        elif timeType == "HOUR":
            m = re.match(r'(\d{4}-\d{2}-\d{2})\D*(\d{1,2})', timeString)
            if m:
                timeString = f"{m.group(1)} {int(m.group(2)):02d}"
        elif timeType in ["MONTH", "DAY", "YEAR"]:
            m = re.match(r'(\d{4}-\d{2}-\d{2}|\d{4}-\d{2}|\d{4})', timeString)
            if m:
                timeString = m.group(1)

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
        "本周",
        "下周的轧制水耗",
        "昨天早班的热轧蒸汽消耗",
        "明天凌晨2点的轧制水耗",
        "去年12月份的吨钢用水量",
        "2025年第4季度纯水损失率",
        "2025年10月上旬热轧蒸汽消耗"
    ]

    for ti in test_inputs:
        result = loop.run_until_complete(parse_user_input(ti, now))
        print(f"{ti} => {result}")
