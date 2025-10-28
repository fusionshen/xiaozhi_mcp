import datetime

def now_str() -> str:
    """返回当前时间字符串"""
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def format_reply(graph, results):
    """
    根据查询结果生成自然语言回答
    """
    lines = [
        f"🧠 当前时间：{now_str()}",
        f"📊 检索到 {len(graph.indicators)} 个指标："
    ]
    for ind in graph.indicators:
        res = results.get(ind, "无数据")
        lines.append(f"  - {ind}: {res}")
    if not graph.times:
        lines.append("⏰ 未提供时间范围。")
    else:
        t = graph.times[-1]
        lines.append(f"⏰ 时间：{t['timeString']} ({t['timeType']})")
    return "\n".join(lines)
