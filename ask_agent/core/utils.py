import datetime
import socket
import os
import uuid
import matplotlib
# 如果在无显示（headless）环境，确保使用 Agg 后端
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import config

# 项目根目录的 data/images 路径（相对 main.py 启动目录）
IMAGES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "images")

def ensure_images_dir():
    if not os.path.exists(IMAGES_DIR):
        os.makedirs(IMAGES_DIR, exist_ok=True)

def save_diff_chart(image_name: str | None, diffs: list[tuple]) -> str:
    """
    将差值序列 diffs 写为 PNG 文件到 data/images/{image_name}.png。
    - diffs: [(timestamp, diff), ...]
    - image_name: 若 None 则自动生成 uuid4 名称（不含扩展名）
    返回：图片文件名（无目录），例如 "b7f8a1e3-....png"
    """
    ensure_images_dir()
    if not image_name:
        image_name = str(uuid.uuid4())
    filename = f"{image_name}.png"
    out_path = os.path.join(IMAGES_DIR, filename)

    # 构建图表
    try:
        ts_labels = [t for t, _ in diffs]
        y_values = [d for _, d in diffs]
        plt.figure(figsize=(8, 4))
        plt.plot(ts_labels, y_values, marker='o', linestyle='-')
        plt.axhline(0, color='gray', linestyle='--')
        plt.xticks(rotation=45)
        plt.xlabel("时间")
        plt.ylabel("左指标 - 右指标")
        plt.title("指标差值趋势图")
        plt.tight_layout()
        plt.savefig(out_path, format="png")
        plt.close()
    except Exception:
        # 确保文件不存在或删除残留
        if os.path.exists(out_path):
            try:
                os.remove(out_path)
            except Exception:
                pass
        raise
    
    # 自动探测 IP + 固定端口
    host = get_local_ip() if config.HOST == "0.0.0.0" else config.HOST
    port = config.PORT or 9001
    base = f"http://{host}:{port}"
    return f"{base}/images/{filename}"  # e.g. 'uuid.png'

def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # 连接一个不存在的地址即可用来探测网卡 IP
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
    except:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip

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
