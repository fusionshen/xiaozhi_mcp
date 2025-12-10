# app/domains/energy/ask/reply_templates.py
from app  import core

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
        "| 序号 | 指标名称 | 公式 | 匹配信息 |",
        "|------|-----------|-----------|----------|",
    ]
    for _, c in enumerate(candidates[:TOP_N], 1):
        rows.append(f"| {c['number']} | {c['FORMULANAME']} | {c['FORMULAID']} | 匹配度 {c.get('score',0):.4f} |")

    table = "\n".join(rows)
    return f"{header}{table}\n\n---\n\n请直接回复编号，例如： **1**，或者输入更精确的指标名称进行更优匹配 😊"

def reply_formula_name_ambiguous(indicator, fuzzy_matches):
    header = f"""通过 **「{indicator}」** 进一步筛选，下面是最接近的几个。  
您可以从下面列表中选择对应的编号👇

---

### 🔍 筛选后可选指标列表
"""

    rows = [
        "| 序号 | 指标名称 | 公式 | 匹配信息 |",
        "|------|-----------|-----------|----------|",
    ]
    for _, c in enumerate(fuzzy_matches, 1):
        rows.append(f"| {c['number']} | {c['FORMULANAME']} | {c['FORMULAID']} | 匹配度 {c.get('score',0):.4f} |")

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

def reply_time_range_normalized_error():
    return "您提供的时间已经是最小粒度，无法提取用于趋势分析的时间范围，请重新输入，例如 '2025-01~2025-09'、'本月'。"

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
            img_url = core.utils.save_multi_series_chart(image_name, multi_series_data, title="多指标趋势", ma_window=0, enable_smooth=False, mark_extrema=False)
            chart_md = f"\n\n#### 📈 多指标趋势图\n\n![]({img_url})"
        except Exception as e:
            chart_md = f"\n\n⚠️ 趋势图生成失败：{e}"

    return f"### ✅ 批量查询结果\n\n{table_md}\n\n{chart_md}\n\n如需继续查询其他指标，随时告诉我～"

def reply_compare(left_entry: dict, right_entry: dict, analysis: str, image_name: str | None = None) -> str:
    """
    指标对比（时间相同 / 时间不同的两种模式自动切换）
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

    # 预处理
    left_vals = _get_value_list(left_entry)
    right_vals = _get_value_list(right_entry)

    if left_vals is None or right_vals is None:
        return analysis

    left_indicator = left_entry.get("indicator", "")
    right_indicator = right_entry.get("indicator", "")
    left_time = left_entry.get("timeString")
    right_time = right_entry.get("timeString")

    # 是否是时间区间
    is_range = "~" in (left_time or "")

    # ============================================================
    # 公共：生成 “差值列表” 与 “表格行”
    # ============================================================
    def build_diff_table(left_label: str, right_label: str):
        """返回：(table_md, diffs_list)"""

        timestamps = sorted(
            {t for t, _ in left_vals} | {t for t, _ in right_vals},
            key=lambda x: str(x)
        )

        rows = [
            f"| 时间 | {left_label} | {right_label} | 差值 | 对比 |",
            "|------|--------|--------|------|------|"
        ]

        diffs = []

        for t in timestamps:
            lv = next((v for ts, v in left_vals if ts == t), None)
            rv = next((v for ts, v in right_vals if ts == t), None)

            lv_s = f"{lv:.4f}" if isinstance(lv, (int, float)) else str(lv) if lv is not None else "-"
            rv_s = f"{rv:.4f}" if isinstance(rv, (int, float)) else str(rv) if rv is not None else "-"

            if lv is None or rv is None:
                diff_s = "-"
                direction = "⚠️ 缺少数据"
            else:
                diff = lv - rv
                diffs.append((t, diff))
                diff_s = f"{diff:+.4f}"
                direction = "↑ 左更高" if diff > 0 else "↓ 左更低" if diff < 0 else "— 持平"

            rows.append(f"| {t} | {lv_s} | {rv_s} | {diff_s} | {direction} |")

        return "\n".join(rows), diffs

    # ============================================================
    # 公共：生成文字总结
    # ============================================================
    def build_summary(prefix: str, diffs: list):
        """prefix 为第一行叙述，diffs 为 [(t, diff)]"""
        lines = [prefix]

        if not diffs:
            lines.append("⚠️ 数据不足，无法计算差值。")
            return "\n".join(lines)

        # 区间 → 做平均值/最大/最小分析
        if is_range:
            values = [d for _, d in diffs]
            avg_d = sum(values) / len(values)
            max_d, min_d = max(values), min(values)
            max_t = next(t for t, d in diffs if d == max_d)
            min_t = next(t for t, d in diffs if d == min_d)

            lines.append(
                f"平均差值：{avg_d:+.4f}；"
                f"最大差值 {max_d:+.4f} 出现在 {max_t}；"
                f"最小差值 {min_d:+.4f} 出现在 {min_t}。"
            )
        else:
            # 单点
            _, d = diffs[0]
            if d > 0:
                lines.append(f"左指标高于右指标，差值为 {d:+.4f}。")
            elif d < 0:
                lines.append(f"左指标低于右指标，差值为 {d:+.4f}。")
            else:
                lines.append("两指标持平。")

        return "\n".join(lines)

    # ============================================================
    # 公共：可选折线图
    # ============================================================
    def build_chart(diffs):
        if not (diffs and is_range):
            return ""
        try:
            img_url = core.utils.save_diff_chart(image_name, diffs)
            return f"\n\n#### 📈 差值趋势图\n\n![]({img_url})"
        except Exception as e:
            return f"\n\n⚠️ 折线图生成失败：{e}"

    # ============================================================
    # 模式 A：指标相同 + 时间不同（切换维度）
    # ============================================================
    if left_indicator == right_indicator and left_time != right_time:
        left_label = f"左指标-{left_time}"
        right_label = f"右指标-{right_time}"
        table_md, diffs = build_diff_table(left_label, right_label)

        prefix = f"对比 **{left_indicator}** 在 **{human_time(left_time, left_entry.get('timeType'))}** 与 **{human_time(right_time, right_entry.get('timeType'))}** 的差异。"
        summary_md = build_summary(prefix, diffs)
        chart_md = build_chart(diffs)

        return f"### 📊 指标对比结果\n\n{table_md}\n\n### 📝 对比总结\n\n{summary_md}{chart_md}"

    # ============================================================
    # 模式 B：指标不同 + 时间相同（原逻辑）
    # ============================================================
    left_label = f"左指标-{left_indicator}"
    right_label = f"右指标-{right_indicator}"
    table_md, diffs = build_diff_table(left_label, right_label)

    prefix = f"对比 **{left_indicator}** 与 **{right_indicator}**，时间：{human_time(left_time, left_entry.get('timeType'))}。"
    summary_md = build_summary(prefix, diffs)
    chart_md = build_chart(diffs)

    return f"### 📊 指标对比结果\n\n{table_md}\n\n### 📝 对比总结\n\n{summary_md}{chart_md}"

def reply_analysis(entries_results: list, analysis: str | None, image_name: str | None = None):
    """
    统一的人性化 Markdown 输出（兼容单条/多条指标，单条时保留 reply_success_single 的展示风格，但不直接 return）：
    - entries_results: list of indicator entries (same structure as in graph/node)
    - analysis: LLM 生成的趋势分析文本（放在最后）
    - image_name: 可选图片名称（省去随机名生成）
    """
    if not entries_results:
        return "没有成功的查询结果。"

    # 如果只有一条结果，则尽量保留 reply_success_single 的输出风格
    if len(entries_results) == 1:
        entry = entries_results[0]
        t = human_time(entry.get("timeString"), entry.get("timeType"))

        result = entry.get("value") or None

        # -------- result is None --------
        if result is None:
            # 以单值样式渲染，但仍生成空图/无图（因为没有数值点）
            table_md = (
                f"### ✅ 查询结果\n\n"
                f"- 指标：**{entry.get('indicator')}**\n"
                f"- 公式：**{entry.get('formula')}**\n"
                f"- 时间：**{t}**\n"
                f"- 数值：**（该时间段暂无数据）**\n\n"
            )

            chart_md = ""  # 无数据点，不画图
            summary_md = f"\n---\n### 🧠 趋势总结\n{analysis}" if analysis else ""
            return f"{table_md}{chart_md}{summary_md}\n如需继续查询其他指标，随时告诉我～"

        # -------- result is dict (single scalar) --------
        if isinstance(result, dict):
            value = result.get("value") or next(iter(result.values()), None)
            unit = result.get("unit", "")
            value_str = f"**{value} {unit}**" if value is not None else "（该时间段暂无数据）"

            table_md = (
                f"### ✅ 查询结果\n\n"
                f"- 指标：**{entry.get('indicator')}**\n"
                f"- 公式：**{entry.get('formula')}**\n"
                f"- 时间：**{t}**\n"
                f"- 数值：**{value_str}**\n\n"
            )

            chart_md = ""  # 单值无法画时间序列图
            summary_md = f"\n---\n### 🧠 趋势总结\n{analysis}" if analysis else ""
            return f"{table_md}{chart_md}{summary_md}\n如需继续查询其他指标，随时告诉我～"

        # -------- result is list (time series) --------
        if isinstance(result, list) and result:
            # 构建时间序列表格（与原 reply_success_single 保持一致）
            rows = ["| 时间 | 数值 |", "|------|------|"]
            series_data = []  # 用于画图的 list[(timestamp, float)]
            for r in result:
                timestamp = r.get("clock") or r.get("time") or r.get("timestamp") or ""
                v = r.get("itemValue") or r.get("value") or r.get("v")
                display_v = v if v is not None else "暂无数据"
                rows.append(f"| {timestamp} | {display_v} |")

                # 尝试解析为数值用于画图
                if v is not None:
                    try:
                        series_data.append((timestamp, float(v)))
                    except:
                        # 非数值用 nan 占位，不放入 series_data
                        pass

            table_md = (
                f"### ✅ 查询结果（时间序列）\n\n"
                f"- 指标：**{entry.get('indicator')}**\n"
                f"- 公式：**{entry.get('formula')}**\n"
                f"- 时间：**{t}**\n\n"
                f"#### 📊 数据列表\n"
                f"{chr(10).join(rows)}\n\n"
            )

            # 画图（即便只有一条指标也画）
            chart_md = ""
            if series_data:
                multi_series_data = {entry.get("indicator", "指标"): series_data}
                try:
                    img_url = core.utils.save_multi_series_chart(image_name, multi_series_data, title=entry.get("indicator", "趋势图"))
                    chart_md = f"\n#### 📈 趋势图\n\n![]({img_url})\n"
                except Exception as e:
                    chart_md = f"\n⚠️ 趋势图生成失败：{e}\n"

            summary_md = f"\n---\n### 🧠 趋势总结\n{analysis}" if analysis else ""
            return f"{table_md}{chart_md}{summary_md}\n如需继续查询其他指标，随时告诉我～"

        # -------- 其他未知类型 --------
        table_md = (
            f"### ✅ 查询结果\n\n"
            f"- 指标：**{entry.get('indicator')}**\n"
            f"- 公式：**{entry.get('formula')}**\n"
            f"- 时间：**{t}**\n"
            f"- 数值：**{result}**\n\n"
        )
        summary_md = f"\n---\n### 🧠 趋势总结\n{analysis}" if analysis else ""
        return f"{table_md}{summary_md}\n如需继续查询其他指标，随时告诉我～"

    # --------------------------
    # 多指标情况（len >= 2）
    # --------------------------
    headers = ["指标", "公式", "时间", "数值"]
    rows = ["| " + " | ".join(headers) + " |", "|------|------|------|------|"]

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
                timestamp = r.get("clock") or r.get("time") or r.get("timestamp") or ""
                v = r.get("itemValue") or r.get("value") or r.get("v") or None
                lines.append(f"{timestamp}: {v if v is not None else '暂无数据'}")
                if v is not None:
                    try:
                        series_data.append((timestamp, float(v)))
                    except:
                        # 非数值忽略
                        pass
            value_str = "<br>".join(lines)
            if series_data:
                multi_series_data[indicator_name] = series_data
        else:
            value_str = str(result)

        rows.append("| " + " | ".join([indicator_name, formula, t, value_str]) + " |")

    table_md = "\n".join(rows)
    chart_md = ""
    if multi_series_data:
        try:
            img_url = core.utils.save_multi_series_chart(image_name, multi_series_data, title="多指标趋势")
            chart_md = f"\n\n#### 📈 多指标趋势图\n\n![]({img_url})"
        except Exception as e:
            chart_md = f"\n\n⚠️ 趋势图生成失败：{e}"

    summary_md = f"\n\n---\n### 🧠 趋势总结\n{analysis}" if analysis else ""
    # 趋势箭头计算
    def compute_trend_arrow(series: list[tuple]):
        """
        输入：[(timestamp, value)...]
        输出："📈 上升", "📉 下降", "➖ 持平"
        """
        vals = [v for _, v in series if isinstance(v, (int, float))]
        if len(vals) < 2:
            return "➖ 数据不足"

        start, end = vals[0], vals[-1]
        if end > start:
            return f"📈 上升（{((end-start)/start)*100:.1f}%）"
        elif end < start:
            return f"📉 下降（{((end-start)/start)*100:.1f}%）"
        else:
            return "➖ 持平"
    # 趋势箭头总结
    if multi_series_data:
        trend_summary = []
        for name, series in multi_series_data.items():
            trend_summary.append(f"- **{name}**：{compute_trend_arrow(series)}")

        arrows_md = "\n".join(trend_summary)
        chart_md = f"\n\n### 趋势方向\n{arrows_md}\n" + chart_md

    return f"### ✅ 批量查询结果\n\n{table_md}\n\n{chart_md}{summary_md}\n\n如需继续查询其他指标，随时告诉我～"
