# app/domains/energy/llm/llm_time_range_normalizer.py
from datetime import datetime
import calendar
import json
from app import core    

"""
目标：
- 保持原设计：当输入不是范围（不包含 "~"）时，让 LLM 扩展为明确范围（包含 "~"）。
- 强制 LLM 执行“降级规则”（如 MONTH -> DAY），并在 prompt 中把优先级规则写清楚，消除互相冲突。
- 明确要求 LLM 必须按公历计算月份天数（包括闰年），并返回严格 JSON。
- 为防止模型出错，增加 Python 端的输出校验与自动修正（仅用于修正日期末日错误或格式问题）。
- 返回格式严格：
    { "timeString": "yyyy-mm-dd~yyyy-mm-dd" 或 "yyyy-mm~yyyy-mm", "timeType": "DAY/MONTH/HOUR/..." }
  timeType 要按强制降级结果返回（例如 MONTH 输入必须返回 timeType "DAY" 且 timeString 包含日级范围）。
"""

# 强制降级映射（当 LLM 扩展后，最终 timeType 应为这个映射的值）
FORCED_DOWNGRADE = {
    "YEAR": "MONTH",
    "QUARTER": "MONTH",
    "MONTH": "DAY",
    "WEEK": "DAY",
    "TENDAYS": "DAY",
    "DAY": "HOUR",
    "HOUR": "HOUR",
    "SHIFT": "SHIFT",
}

# Helper: get last day of month
def month_last_day(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]

# Validate & fix LLM output (ensure calendar correctness & enforce downgrade)
def validate_and_fix(output: dict, original_timeType: str):
    """
    Robust validator and fixer for LLM output.
    - Accepts hour-granularity ranges like "YYYY-MM-DD HH~YYYY-MM-DD HH".
    - Enforces forced downgrade mapping (FORCED_DOWNGRADE).
    - Ensures calendar correctness (month end days) and clamps hours to [0,23].
    - If LLM omitted hour but final timeType == "HOUR", fills left hour=00, right hour=23.
    Returns normalized dict: {"timeString": "...~...", "timeType": "..."}
    """

    def parse_date_time(token: str):
        """
        Parse token allowing:
         - YYYY
         - YYYY-MM
         - YYYY-MM-DD
         - YYYY-MM-DD HH
         - YYYY-MM-DD HH:MM
         - YYYY-MM-DDTHH or YYYY-MM-DDTHH:MM
        Returns tuple (y:int or None, m:int or None, d:int or None, h:int or None)
        """
        if not isinstance(token, str):
            return (None, None, None, None)
        s = token.strip()
        # normalize 'T' to space
        s = s.replace("T", " ")
        parts = s.split()
        date_part = parts[0] if parts else ""
        time_part = parts[1] if len(parts) > 1 else None

        date_fields = date_part.split("-")
        try:
            if len(date_fields) == 1 and date_fields[0] != "":
                y = int(date_fields[0])
                return (y, None, None, None)
            if len(date_fields) == 2:
                y = int(date_fields[0]); m = int(date_fields[1])
                return (y, m, None, None)
            if len(date_fields) == 3:
                y = int(date_fields[0]); m = int(date_fields[1]); d = int(date_fields[2])
            else:
                return (None, None, None, None)
        except Exception:
            return (None, None, None, None)

        h = None
        if time_part:
            # time_part could be "HH" or "HH:MM" or "HH:MM:SS"
            try:
                h = int(str(time_part).split(":")[0])
            except Exception:
                h = None

        return (y, m, d, h)

    def clamp_day(y, m, d):
        """Clamp day to valid month days; if any part None return None."""
        if y is None or m is None or d is None:
            return (y, m, d)
        last = month_last_day(y, m)
        if d > last:
            d = last
        if d < 1:
            d = 1
        return (y, m, d)

    def clamp_hour(h):
        if h is None:
            return None
        if h < 0:
            return 0
        if h > 23:
            return 23
        return h

    # prepare result skeleton
    res = {
        "timeString": output.get("timeString"),
        "timeType": (output.get("timeType") or "").upper()
    }

    # fallback if invalid format / missing ~
    if not isinstance(res["timeString"], str) or "~" not in res["timeString"]:
        point = output.get("timeString", "")
        tt = (output.get("timeType") or original_timeType).upper()
        return {"timeString": point, "timeType": tt}

    # ensure uppercase timeType
    if not res["timeType"]:
        res["timeType"] = original_timeType.upper()
    res["timeType"] = res["timeType"].upper()

    forced = FORCED_DOWNGRADE.get(original_timeType.upper(), original_timeType.upper())
    # enforce forced downgrade (but allow HOUR if forced is HOUR)
    if forced != res["timeType"]:
        # If model returned HOUR but forced is not HOUR, still override to forced,
        # except when original_timeType itself is DAY and model returned HOUR (allowed).
        # We allow case: original DAY -> model HOUR (keep HOUR). Otherwise override.
        if not (original_timeType.upper() == "DAY" and res["timeType"] == "HOUR"):
            res["timeType"] = forced

    left_raw, right_raw = [s.strip() for s in res["timeString"].split("~", 1)]

    # parse both sides (support hour)
    l_y, l_m, l_d, l_h = parse_date_time(left_raw)
    r_y, r_m, r_d, r_h = parse_date_time(right_raw)

    # If final type required is DAY (no hours)
    if res["timeType"] == "DAY":
        # promote month/year-only to day; if hours provided drop them and use date only
        # left defaults: yyyy-mm-01 or yyyy-01-01; right defaults: yyyy-mm-last or yyyy-12-31
        if l_d is None:
            if l_m is None:
                l_m = 1
            l_d = 1
        if r_d is None:
            if r_m is None:
                r_m = 12
                r_d = 31
            else:
                r_d = month_last_day(r_y, r_m)
        # clamp day to valid ranges
        l_y, l_m, l_d = clamp_day(l_y, l_m, l_d)
        r_y, r_m, r_d = clamp_day(r_y, r_m, r_d)
        left_fixed = f"{l_y:04d}-{l_m:02d}-{l_d:02d}"
        right_fixed = f"{r_y:04d}-{r_m:02d}-{r_d:02d}"
        res["timeString"] = f"{left_fixed}~{right_fixed}"
        return res

    # If final type required is MONTH (YYYY-MM~YYYY-MM)
    if res["timeType"] == "MONTH":
        if l_m is None:
            l_m = 1
        if r_m is None:
            r_m = 12
        left_fixed = f"{l_y:04d}-{l_m:02d}"
        right_fixed = f"{r_y:04d}-{r_m:02d}"
        res["timeString"] = f"{left_fixed}~{right_fixed}"
        return res

    # If final type required is HOUR (accept and normalize hour granularity)
    if res["timeType"] == "HOUR":
        # left: ensure y,m,d present
        if l_d is None:
            if l_m is None:
                l_m = 1
            l_d = 1
        if r_d is None:
            if r_m is None:
                r_m = 12
            # if r has month but no day -> set to last day
            r_d = month_last_day(r_y, r_m)
        # clamp days
        l_y, l_m, l_d = clamp_day(l_y, l_m, l_d)
        r_y, r_m, r_d = clamp_day(r_y, r_m, r_d)

        # Hours: if missing, default left=0, right=23 (common convention)
        l_h = clamp_hour(l_h) if l_h is not None else 0
        r_h = clamp_hour(r_h) if r_h is not None else 23

        # If left date > right date, it's an error — but we'll keep as-is (higher-level can assert)
        left_fixed = f"{l_y:04d}-{l_m:02d}-{l_d:02d} {l_h:02d}"
        right_fixed = f"{r_y:04d}-{r_m:02d}-{r_d:02d} {r_h:02d}"
        res["timeString"] = f"{left_fixed}~{right_fixed}"
        return res

    # For SHIFT or other types: try to preserve granularity but ensure day clamping where possible
    # Clamp day if present
    if l_d is not None:
        l_y, l_m, l_d = clamp_day(l_y, l_m, l_d)
    if r_d is not None:
        r_y, r_m, r_d = clamp_day(r_y, r_m, r_d)

    # reconstruct preserving best-known granularity
    def reconstruct(y, m, d, h):
        if d is None and m is None:
            return f"{y:04d}"
        if d is None:
            return f"{y:04d}-{m:02d}"
        if h is None:
            return f"{y:04d}-{m:02d}-{d:02d}"
        return f"{y:04d}-{m:02d}-{d:02d} {h:02d}"

    left_fixed = reconstruct(l_y, l_m, l_d, l_h)
    right_fixed = reconstruct(r_y, r_m, r_d, r_h)
    res["timeString"] = f"{left_fixed}~{right_fixed}"
    return res

# Build the strict prompt for the LLM to do expansion
def _make_prompt(timeString: str, timeType: str, now: datetime) -> str:
    now_str = now.strftime("%Y-%m-%d %H:%M")
    # Explicit, no-ambiguity instructions. Examples included (including month end days).
    return f"""
你是“时间范围标准化助手”。系统当前时间：{now_str}

任务：**当用户输入的 timeString 不包含 "~" 时**，你必须**按下列强制规则**把输入扩展为明确的区间（包含 "~"），并按照降级规则设置返回的 timeType（全大写）。

**最重要的强制规则（优先级最高）**：
1. 当输入 timeType 为 HOUR 或 SHIFT：**绝对不扩展或降级**，必须**原样返回**输入的 timeString 与 timeType（保持原格式）。
2. 降级必须执行：YEAR→MONTH、QUARTER→MONTH、MONTH→DAY、WEEK→DAY、TENDAYS→DAY、DAY→HOUR。你**必须**把返回的 timeType 设置为降级后的值（例如输入 MONTH，返回 timeType 必须是 DAY）。
3. 所有日期范围必须遵循 **公历（格里高利历）** 的真实天数：2 月按闰年为 29 天或 28 天，3 月为 31 天，4 月 30 天等。**不得随意使用 30 或 31 替代**。
4. 不允许返回不存在的日期（例如 2022-02-30、2022-04-31）。
5. 返回必须是纯 JSON，且**不得包含额外字段或说明文字**，仅返回：
   {{
     "timeString": "left~right",
     "timeType": "..." 
   }}

**区间扩展规则（当 timeString 不含 "~"）**：
- YEAR (e.g., "2024"):
  - 如果输入年份 == 当前年份：返回 `"YYYY-01~YYYY-<CURRENT_MONTH>"`，timeType -> "MONTH"。
  - 如果输入年份 != 当前年份：返回该年完整自然年 `"YYYY-01~YYYY-12"`，timeType -> "MONTH"。
- QUARTER (e.g., "2025-Q2"):
  - 返回对应季度月份区间 `"YYYY-04~YYYY-06"`，timeType -> "MONTH"。
- MONTH (e.g., "2023-06"):
  - 返回该整月的天区间（精确到日），例如 `"2023-06-01~2023-06-30"`（注意 30/31 根据月份确定），timeType -> "DAY"。
- WEEK (ISO, e.g., "2025-W15"):
  - 返回该周的自然日期（周一~周日），例如 `"2025-04-07~2025-04-13"`，timeType -> "DAY"。
- TENDAYS (格式如 "2025-10上旬/中旬/下旬"):
  - 上旬 -> 01~10，中旬 -> 11~20，下旬 -> 21~月末，timeType -> "DAY"。
- DAY (e.g., "2024-10-03"):
  - 返回 `"YYYY-MM-DD 00~YYYY-MM-DD 23"`，timeType -> "HOUR"。
- 如果输入本身已经包含 "~"，视为用户显式区间，**不得修改或降级**，直接返回原样。

**返回格式严格示例**：
- 输入: timeString="2022", timeType="YEAR" -> 输出:
  {{ "timeString": "2022-01~2022-12", "timeType": "MONTH" }}
- 输入: timeString="2025-03", timeType="MONTH" -> 输出:
  {{ "timeString": "2025-03-01~2025-03-31", "timeType": "DAY" }}
- 输入: timeString="2024-02", timeType="MONTH" -> 输出:
  {{ "timeString": "2024-02-01~2024-02-29", "timeType": "DAY" }}

现在请仅返回 JSON，不要做任何额外解释。用户输入："timeString":"{timeString}" , "timeType":"{timeType}"
"""

# 主函数：调用 LLM，然后校验/修正
async def normalize_time_range(timeString: str, timeType: str, now: datetime = None):
    """
    保持外部接口不变：返回 { "timeString": "...~...", "timeType": "..." }
    """
    if now is None:
        now = datetime.now()

    # 如果已经是范围，直接返回（不得修改）
    if "~" in timeString:
        return {"timeString": timeString, "timeType": timeType}

    prompt = _make_prompt(timeString, timeType, now)

    # 交给 LLM 生成扩展区间（LLM 必须返回 JSON）
    raw = await core.safe_llm_parse(prompt)

    # safe_llm_parse 预期返回 dict; 但我们要防御性处理
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except Exception:
            # 如果解析失败，把原始结构传回给检测/修正函数
            parsed = {"timeString": raw, "timeType": timeType}
    elif isinstance(raw, dict):
        parsed = raw
    else:
        parsed = {"timeString": str(raw), "timeType": timeType}

    # 验证并修正（确保月份天数正确、确保强制降级返回）todo: 因为参数timeString是标准格式，所以这里用直接代码修正稳定性会更好！
    fixed = validate_and_fix(parsed, timeType)

    return fixed
