# core/reply_templates.py
def human_time(timeString: str, timeType: str):
    """
    将解析器输出的 timeString + timeType 转换为
    更友好的自然语言，用于展示在前端（支持 Markdown）。

    示例：
        DAY: "2025-10-14" → "2025年10月14日"
        WEEK: "2025 W41" → "2025年第 41 周"
        MONTH: "2025-09" → "2025年9月"
        QUARTER: "2024 Q3" → "2024年第 3 季度"
        TENDAYS: "2025-10 下旬" → "2025年10月下旬"
        SHIFT: "2025-10-20 夜班" → "2025年10月20日 夜班"
        HOUR: "2025-10-20 14" → "2025年10月20日 14 点"
        区间: "2025-01~2025-06" → "2025年1月 ~ 2025年6月"
    """

    if not timeString or not timeType:
        return "（时间未指定）"

    # ---------- 区间解析 ----------
    if "~" in timeString:
        start, end = timeString.split("~", 1)
        return f"{_fmt_single_time(start, timeType)} ~ {_fmt_single_time(end, timeType)}"

    # ---------- 单点时间 ----------
    return _fmt_single_time(timeString, timeType)

def _fmt_single_time(ts: str, timeType: str):
    """内部函数：处理单一时间点"""

    # DAY
    if timeType == "DAY":
        y, m, d = ts.split("-")
        return f"{y}年{int(m)}月{int(d)}日"

    # HOUR
    if timeType == "HOUR":
        date, hour = ts.split(" ")
        y, m, d = date.split("-")
        return f"{y}年{int(m)}月{int(d)}日 {int(hour)}点"

    # SHIFT
    if timeType == "SHIFT":
        date, shift = ts.split(" ")
        y, m, d = date.split("-")
        return f"{y}年{int(m)}月{int(d)}日 {shift}"

    # WEEK
    if timeType == "WEEK":
        y, wk = ts.split(" ")
        wk = wk.replace("W", "")
        return f"{y}年第 {int(wk)} 周"

    # MONTH
    if timeType == "MONTH":
        y, m = ts.split("-")
        return f"{y}年{int(m)}月"

    # QUARTER
    if timeType == "QUARTER":
        y, q = ts.split(" ")
        q = q.replace("Q", "")
        return f"{y}年第 {int(q)} 季度"

    # TENDAYS（上旬 / 中旬 / 下旬）
    if timeType == "TENDAYS":
        y_m, ten = ts.split(" ")
        y, m = y_m.split("-")
        return f"{y}年{int(m)}月{ten}"

    # YEAR
    if timeType == "YEAR":
        return f"{ts}年"

    return ts

def reply_ask_indicator():
    return """我还不太确定您想查询哪个指标 😊  
能再告诉我一下具体的指标名称吗？"""

def reply_ask_time(indicator):
    return f"""好的，我已经找到了您要查的指标：**{indicator}**  
请告诉我您想查询的时间，例如：

- 今天  
- 昨天  
- 2025-11-20  
- 上个月  

我就能继续为您查询啦 😊"""

def reply_no_formula():
    return "我找不到对应的指标公式，看起来这个名字我还不认识。\n可以再换一个常用的指标名称试试吗？"

def reply_candidates(indicator, candidates, TOP_N=5):
    header = f"""我没有找到和 **「{indicator}」** 完全一致的指标，下面是最接近的几个。  
您可以从下面列表中选择对应的编号👇

---

### 🔍 可选指标列表
"""

    rows = [
        "| 序号 | 指标名称 | 匹配信息 |",
        "|------|-----------|----------|",
    ]
    for i, c in enumerate(candidates[:TOP_N], 1):
        rows.append(f"| {i} | {c['FORMULANAME']} | 匹配度 {c.get('score',0):.1f} |")

    table = "\n".join(rows)
    return f"{header}{table}\n\n---\n\n请直接回复编号，例如： **1**，或者输入更精确的指标名称进行更优匹配 😊"

def reply_no_formula(indicator):
    return f"""抱歉，我没有找到与 **「{indicator}」** 相关的匹配指标。  

您可以尝试提供更完整或更准确的指标名称，我再帮您查一次 😊"""

def reply_success_single(indicator: dict):
    """
    根据原始查询结果生成人性化 Markdown 回复。
    - indicator: 指标名称
    - result: platform_api 查询返回，可能是 dict / list / None
    - timeString: 查询时间或区间
    - timeType: 查询时间类型
    """
    t = human_time(indicator.get("timeString"), indicator.get("timeType"))

    # -------------------- 处理不同类型 --------------------
    result = indicator.get("value") or None
    # 无数据
    if result is None:
        value_str = "（该时间段暂无数据）"
        return f"""### ✅ 查询结果

- 指标：**{indicator.get("indicator")}**
- 公式：**{indicator.get("formula")}**
- 时间：**{t}**
- 数值：**{value_str}**

如需继续查询其他指标，随时告诉我～
"""

    # 单值 dict
    if isinstance(result, dict):
        value = result.get("value") or next(iter(result.values()), None)
        unit = result.get("unit", "")
        value_str = f"**{value} {unit}**" if value is not None else "（该时间段暂无数据）"
        return f"""### ✅ 查询结果

- 指标：**{indicator.get("indicator")}**
- 公式：**{indicator.get("formula")}**
- 时间：**{t}**
- 数值：**{value_str}**

如需继续查询其他指标，随时告诉我～
"""

    # 列表返回（时间序列）
    if isinstance(result, list) and result:
        # 第一条记录作为 summary
        value = (
            result[0].get("itemValue") 
            or result[0].get("value") 
            or result[0].get("v")
        )

        # 构建 Markdown 表格
        rows = ["| 时间 | 数值 |", "|------|------|"]
        for r in result:
            timestamp = r.get("clock") or r.get("time") or r.get("timestamp")
            v = (
                r.get("itemValue") 
                or r.get("value") 
                or r.get("v")
                or "暂无数据"
            )
            rows.append(f"| {timestamp} | {v} |")

        table_md = "\n".join(rows)

        return f"""### ✅ 查询结果（时间序列）

- 指标：**{indicator.get("indicator")}**
- 公式：**{indicator.get("formula")}**
- 时间：**{t}**

#### 📊 数据列表
{table_md}

如需继续查询其他指标，随时告诉我～
"""

    # 其他未知类型
    return f"""### ✅ 查询结果

- 指标：**{indicator.get("indicator")}**
- 公式：**{indicator.get("formula")}**
- 时间：**{t}**
- 数值：**{result}**

如需继续查询其他指标，随时告诉我～
"""

def reply_api_error():
    return "查询时遇到了一点小问题，我这边暂时拿不到平台的数据。\n您可以稍后再试一次。"

def reply_ask_time_unknown():
    return "我不太确定您说的时间范围，可以再具体一点吗？"

def reply_time_parse_error():
    return "我没能理解时间，请再试一次，例如：昨天 / 上周 / 2024年10月。"

def reply_no_formula_in_context():
    return (
        "我这边没有找到可选的公式，看起来当前的指标信息不完整 🤔\n"
        "能再告诉我一次您想查询的指标名称吗？我会重新帮您匹配～"
    )

def reply_invalid_formula_index(max_n: int):
    return (
        f"编号需要在 **1 ~ {max_n}** 之间哦 😊\n"
        f"请再输入一次对应的序号，我会帮您选定正确的指标公式～"
    )

def reply_compare_no_left_data():
    return "⚠️ 无可用的参考指标，请先进行至少一次查询以便进行对比。"

def reply_compare_no_data():
    return "⚠️ 当前没有足够的数据进行对比，请先查询至少两条指标结果。"

def reply_compare_too_many_candidates():
    return "⚠️ 当前只支持两项对比，请提供两个要对比的指标，或改问趋势/分析。"

def reply_compare_single_missing_time(indicator):
    return f"好的，要对比 **{indicator}**，请告诉我具体的时间，我才能为您完成对比 😊"

def simple_reply(indicator_entry):
    """
    根据 indicator_entry 和 result 生成简洁版 reply
    """
    indicator = indicator_entry.get("indicator")
    time_str = indicator_entry.get("timeString")
    time_type = indicator_entry.get("timeType")
    result = indicator_entry.get("value")
    if result is None:
        return f"✅ {indicator} 在 {time_str} ({time_type}) 的值暂无数据。"

    if isinstance(result, dict):
        val = result.get("value") or next(iter(result.values()), None)
        unit = result.get("unit", "")
        return f"✅ {indicator} 在 {time_str} ({time_type}) 的值是 {val} {unit}"

    if isinstance(result, list) and result:
        lines = [f"{r.get('clock') or r.get('time') or r.get('timestamp')}: {r.get('itemValue') or r.get('value') or r.get('v')}" for r in result]
        return f"✅ {indicator} 在 {time_str} ({time_type}) 的查询结果:\n" + "\n".join(lines)

    return f"✅ {indicator} 在 {time_str} ({time_type}) 的查询结果: {result}"

def reply_success_list(entries_results: list, image_name: str | None = None):
    """
    批量查询的人性化 Markdown 输出（支持多指标绘制同一张趋势图）
    """
    from core import utils

    if not entries_results:
        return "没有成功的查询结果。"

    if len(entries_results) == 1:
        return reply_success_single(entries_results[0])

    headers = ["指标", "公式", "时间", "数值"]
    rows = ["| " + " | ".join(headers) + " |", "|------|------|------|------|"]

    # 用于同图绘制多指标
    multi_series_data = {}

    for entry in entries_results:
        result = entry.get("value")
        indicator_name = entry.get("indicator", "未知指标")
        formula = entry.get("formula", "未知公式")
        t = human_time(entry.get("timeString"), entry.get("timeType"))

        if result is None:
            value_str = "暂无数据"
        elif isinstance(result, dict):
            val = result.get("value") or next(iter(result.values()), None)
            unit = result.get("unit", "")
            value_str = f"{val} {unit}".strip() if val is not None else "暂无数据"
        elif isinstance(result, list) and result:
            lines = []
            series_data = []
            for r in result:
                timestamp = r.get("clock") or r.get("time") or r.get("timestamp")
                v = r.get("itemValue") or r.get("value") or r.get("v") or "暂无数据"
                lines.append(f"{timestamp}: {v}")
                if v != "暂无数据":
                    try:
                        series_data.append((timestamp, float(v)))
                    except:
                        series_data.append((timestamp, v))
            value_str = "<br>".join(lines)
            if series_data and any(isinstance(v, (int, float)) for _, v in series_data):
                multi_series_data[indicator_name] = series_data
        else:
            value_str = str(result)

        row = [indicator_name, formula, t, value_str]
        rows.append("| " + " | ".join(row) + " |")

    table_md = "\n".join(rows)

    chart_md = ""
    if multi_series_data:
        try:
            img_url = utils.save_multi_series_chart(image_name, multi_series_data, title="多指标趋势")
            chart_md = f"\n\n#### 📈 多指标趋势图\n\n![]({img_url})"
        except Exception as e:
            chart_md = f"\n\n⚠️ 趋势图生成失败：{e}"

    return f"### ✅ 批量查询结果\n\n{table_md}\n\n{chart_md}\n\n如需继续查询其他指标，随时告诉我～"

def compare_summary(left_entry: dict, right_entry: dict, image_name: str | None = None) -> str:
    """
    对比并返回 Markdown（表格 + 文本 + 若有则插入 /images/{filename}.png）。
    - left_entry/right_entry:
        {
            "indicator": "...",
            "timeString": "...",
            "timeType": "...",
            "value": 单值/dict(list)/list
        }
    """
    # -------------------------------
    # 解析 value（兼容 单值 / dict / list）
    # -------------------------------
    def _get_value_list(entry):
        val = entry.get("value")

        if val is None or val == "":
            return None

        # dict 格式：{timestamp: value}
        if isinstance(val, dict):
            try:
                items = sorted(val.items(), key=lambda x: str(x[0]))
            except Exception:
                items = list(val.items())
            out = []
            for t, v in items:
                try:
                    out.append((t, float(v)))
                except:
                    out.append((t, v))
            return out

        # list 格式（平台常用时间序列）
        if isinstance(val, list):
            out = []
            for r in val:
                t = r.get("clock") or r.get("time") or r.get("timestamp")
                v = r.get("itemValue") or r.get("value") or r.get("v")
                if t is None or v is None:
                    continue
                try:
                    out.append((t, float(v)))
                except:
                    out.append((t, v))
            return out if out else None

        # 单值
        try:
            return [("单值", float(val))]
        except:
            return [("单值", val)]

    left_vals = _get_value_list(left_entry) or []
    right_vals = _get_value_list(right_entry) or []

    # -------------------------------
    # 生成对比表格（每个时间节点数据 + 差值）
    # -------------------------------
    table_rows = [
        "| 时间 | 左指标 | 右指标 | 差值 | 对比 |",
        "|------|--------|--------|------|------|"
    ]

    timestamps = sorted(
        set([t for t, _ in left_vals] + [t for t, _ in right_vals]),
        key=lambda x: str(x)
    )

    diffs = []

    for t in timestamps:
        lv = next((v for ts, v in left_vals if ts == t), None)
        rv = next((v for ts, v in right_vals if ts == t), None)

        lv_str = f"{lv:.4f}" if isinstance(lv, (int, float)) else str(lv) if lv is not None else "-"
        rv_str = f"{rv:.4f}" if isinstance(rv, (int, float)) else str(rv) if rv is not None else "-"

        if lv is None or rv is None:
            diff_str = "-"
            direction = "⚠️ 缺少数据"
        else:
            diff = lv - rv
            diffs.append((t, diff))
            diff_str = f"{diff:+.4f}"
            if diff > 0:
                direction = "↑ 左指标更高"
            elif diff < 0:
                direction = "↓ 左指标更低"
            else:
                direction = "— 持平"

        table_rows.append(f"| {t} | {lv_str} | {rv_str} | {diff_str} | {direction} |")

    table_md = "\n".join(table_rows)

    # -------------------------------
    # 生成总结文本
    # -------------------------------
    def human_time(time_str, time_type=None):
        return str(time_str) if time_str else "-"

    t_str = human_time(left_entry.get("timeString"), left_entry.get("timeType"))
    left_name = left_entry.get("indicator", "左指标")
    right_name = right_entry.get("indicator", "右指标")

    summary_lines = [f"对比 **{left_name}** 与 **{right_name}**，时间：{t_str}。"]

    is_range = "~" in (left_entry.get("timeString") or "")

    if diffs and is_range:
        values = [d for _, d in diffs]
        avg_diff = sum(values) / len(values)
        max_diff, min_diff = max(values), min(values)
        max_time = next(t for t, d in diffs if d == max_diff)
        min_time = next(t for t, d in diffs if d == min_diff)
        summary_lines.append(
            f"平均差值：{avg_diff:+.4f}；"
            f"最大差值 {max_diff:+.4f} 出现在 {max_time}；"
            f"最小差值 {min_diff:+.4f} 出现在 {min_time}。"
        )
    elif diffs:
        _, diff = diffs[0]
        if diff > 0:
            summary_lines.append(f"左指标高于右指标，差值为 {diff:+.4f}。")
        elif diff < 0:
            summary_lines.append(f"左指标低于右指标，差值为 {diff:+.4f}。")
        else:
            summary_lines.append("两指标持平。")
    else:
        summary_lines.append("⚠️ 数据不足，无法计算差值。")

    summary_md = "\n".join(summary_lines)

    # -------------------------------
    # 可选折线图
    # -------------------------------
    chart_md = ""
    if diffs and is_range:
        try:
            from core import utils
            img_url = utils.save_diff_chart(image_name, diffs)
            chart_md = f"\n\n#### 📈 差值趋势图\n\n![]({img_url})"
        except Exception as e:
            summary_lines.append(f"⚠️ 折线图生成失败：{e}")

    # -------------------------------
    # 返回 Markdown
    # -------------------------------
    return f"### 📊 指标对比结果\n\n{table_md}\n\n### 📝 对比总结\n\n{summary_md}{chart_md}"