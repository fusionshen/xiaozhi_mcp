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

BASE_DIR = os.path.dirname(__file__)
DATA_DIR = os.path.join(config.ROOT_DIR, "data")
IMAGES_DIR = os.path.join(DATA_DIR, "images")
FONTS_DIR = os.path.join(BASE_DIR, "fonts")

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

def save_multi_series_chart(
    image_name: str,
    series_dict: dict[str, list[tuple]],
    title: str = "",
    ma_window: int = 5,          # 移动平均窗口
    enable_smooth: bool = True,  # 是否启用平滑曲线
    mark_extrema: bool = True    # 是否标注最高/最低值
):
    """
    画趋势图（多指标），包含：
    - 自动趋势箭头
    - 平滑曲线（轻量 LOESS）
    - 移动平均线（MA）
    - 标注最大/最小值
    """
    import pandas as pd
    import matplotlib.pyplot as plt
    from scipy.signal import savgol_filter   # 更稳健的平滑
    ensure_images_dir()

    if not image_name:
        image_name = str(uuid.uuid4())
    filename = f"{image_name}.png"
    file_path = os.path.join(IMAGES_DIR, filename)

    if not series_dict:
        raise ValueError("series_dict 为空，无法生成图表")

    # ---------------------------
    # 收集全部时间戳（排序）
    # ---------------------------
    all_ts = sorted({t for series in series_dict.values() for t, _ in series}, key=str)

    plt.figure(figsize=(12, 6))

    for name, series in series_dict.items():
        # ---------------------
        # 原始数据对齐
        # ---------------------
        ts_to_val = {
            t: float(v) if isinstance(v, (int, float)) else np.nan
            for t, v in series
        }
        y = np.array([ts_to_val.get(t, np.nan) for t in all_ts])
        x = np.arange(len(all_ts))

        # 绘制原始折线
        plt.plot(all_ts, y, marker='o', linestyle='-', label=f"{name} 原始")

        # ---------------------
        # 移动平均线
        # ---------------------
        if ma_window > 1 and np.count_nonzero(~np.isnan(y)) > ma_window:
            y_ma = pd.Series(y).rolling(ma_window, min_periods=1).mean().values
            plt.plot(all_ts, y_ma, linestyle='--', alpha=0.8, label=f"{name} MA{ma_window}")

        # ---------------------
        # 平滑曲线（LOESS-lite）
        # ---------------------
        if enable_smooth and np.count_nonzero(~np.isnan(y)) >= 5:
            # 使用 Savitzky-Golay filter 更稳定
            try:
                y_smooth = savgol_filter(pd.Series(y).interpolate().values, 5, 2)
                plt.plot(all_ts, y_smooth, alpha=0.8, label=f"{name} 平滑")
            except:
                pass

        # ---------------------
        # 最大/最小值标注
        # ---------------------
        if mark_extrema and np.count_nonzero(~np.isnan(y)) > 0:
            valid_idx = np.where(~np.isnan(y))[0]
            vmax_idx = valid_idx[np.argmax(y[valid_idx])]
            vmin_idx = valid_idx[np.argmin(y[valid_idx])]

            # 标注最大值
            plt.scatter(all_ts[vmax_idx], y[vmax_idx], color='red')
            plt.text(all_ts[vmax_idx], y[vmax_idx], f"↑Max: {y[vmax_idx]:.2f}", color='red')

            # 标注最小值
            plt.scatter(all_ts[vmin_idx], y[vmin_idx], color='blue')
            plt.text(all_ts[vmin_idx], y[vmin_idx], f"↓Min: {y[vmin_idx]:.2f}", color='blue')

    plt.title(title)
    plt.xlabel("时间")
    plt.ylabel("数值")
    plt.grid(True, linestyle='--', alpha=0.3)

    plt.xticks(rotation=30, ha='right')
    plt.legend(loc="upper left", bbox_to_anchor=(1.01, 1))

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
