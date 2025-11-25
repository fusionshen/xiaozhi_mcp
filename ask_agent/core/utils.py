import datetime
import socket
import os
import uuid
import matplotlib
matplotlib.use("Agg")  # headless 环境
import matplotlib.pyplot as plt
from matplotlib import rcParams
import matplotlib.font_manager as fm
import config
import numpy as np

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
IMAGES_DIR = os.path.join(DATA_DIR, "images")
FONTS_DIR = os.path.join(DATA_DIR, "fonts")

# ================== 中文字体处理 ==================
simhei_path = os.path.join(FONTS_DIR, "SimHei.ttf")

if not os.path.exists(simhei_path):
    raise FileNotFoundError(f"字体文件不存在: {simhei_path}")

# 1. 注册字体
fm.fontManager.addfont(simhei_path)

# 2. 获取字体名称（跨版本兼容）
simhei_name = fm.FontProperties(fname=simhei_path).get_name()

# 3. 强制 matplotlib 使用 SimHei
rcParams["font.family"] = simhei_name
rcParams["font.sans-serif"] = [simhei_name]

# 4. 正确显示负号
rcParams["axes.unicode_minus"] = False

# 默认样式
rcParams['font.size'] = 12
rcParams['legend.fontsize'] = 10
rcParams['xtick.labelsize'] = 10
rcParams['ytick.labelsize'] = 10
rcParams['lines.linewidth'] = 2
rcParams['lines.markersize'] = 6
# ======================================================

def ensure_images_dir():
    if not os.path.exists(IMAGES_DIR):
        os.makedirs(IMAGES_DIR, exist_ok=True)


def save_diff_chart(image_name: str | None, diffs: list[tuple]) -> str:
    """
    生成差值曲线图并返回可访问 URL
    """
    ensure_images_dir()
    if not image_name:
        image_name = str(uuid.uuid4())
    filename = f"{image_name}.png"
    out_path = os.path.join(IMAGES_DIR, filename)

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
        if os.path.exists(out_path):
            try:
                os.remove(out_path)
            except:
                pass
        raise

    return format_file_path(filename)

def format_file_path(filename: str):
    # --------- 关键修复：0.0.0.0 自动检测 IP ---------
    host = get_local_ip() if config.HOST in ["0.0.0.0", "", None] else config.HOST
    port = config.PORT or 9001
    base = f"http://{host}:{port}"
    return f"{base}/images/{filename}"

def save_multi_series_chart(image_name: str, series_dict: dict[str, list[tuple]], title: str = "") -> str:
    """
    保存多指标时间序列折线图到一张图，统一时间轴，缺失点显示为空
    - filename: 图片文件名，例如 '多指标.png'
    - series_dict: {"指标名": [(timestamp, value), ...], ...}
    - title: 图表标题
    返回相对路径 Markdown 可直接引用
    """
    ensure_images_dir()
    if not series_dict:
        raise ValueError("series_dict 为空，无法生成图表")
    
    if not image_name:
        image_name = str(uuid.uuid4())
    filename = f"{image_name}.png"

    file_path = os.path.join(IMAGES_DIR, filename)
    # 统一时间轴
    all_timestamps = sorted({t for series in series_dict.values() for t, _ in series}, key=str)
    plt.figure(figsize=(10, 5))

    for name, series_data in series_dict.items():
        ts_to_val = {t: v if isinstance(v, (int, float)) else np.nan for t, v in series_data}
        y = [ts_to_val.get(t, np.nan) for t in all_timestamps]
        plt.plot(all_timestamps, y, marker='o', linestyle='-', label=name)

    plt.xticks(rotation=30, ha='right')
    plt.title(title)
    plt.xlabel("时间")
    plt.ylabel("数值")
    plt.grid(True, linestyle='--', alpha=0.5)
    plt.legend()
    plt.tight_layout()
    plt.savefig(file_path, dpi=150)
    plt.close()

    return format_file_path(filename)


def get_local_ip():
    """
    自动探测本机可用 IP（非 127.0.0.1）
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
    except:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip


def now_str() -> str:
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


if __name__ == "__main__":
    """
    测试 save_diff_chart 是否能正常输出中文图表
    """
    print("开始测试 save_diff_chart ...")

    diffs = []
    now = datetime.datetime.now()
    for i in range(10):
        ts = (now + datetime.timedelta(minutes=i)).strftime("%H:%M:%S")
        diffs.append((ts, i - 5))

    url = save_diff_chart("test_diff_chart", diffs)
    print("测试完成！图片 URL：", url)
    print("图片文件是否存在：", os.path.exists(os.path.join(IMAGES_DIR, "test_diff_chart.png")))
