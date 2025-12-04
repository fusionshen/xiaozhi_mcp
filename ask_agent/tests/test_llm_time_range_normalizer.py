import asyncio
from datetime import datetime

from core.llm_time_range_normalizer import normalize_time_range

# 固定当前系统时间（测试可控）
# 你也可以设为 None 使用当前真实系统时间
NOW = datetime(2025, 10, 15, 14, 30)


TEST_CASES = [

    # ===== YEAR =====
    ("2025", "YEAR"),
    ("2024", "YEAR"),

    # ===== QUARTER =====
    ("2025-Q1", "QUARTER"),
    ("2025-Q2", "QUARTER"),
    ("2025-Q3", "QUARTER"),
    ("2025-Q4", "QUARTER"),

    # ===== MONTH =====
    ("2024-08", "MONTH"),
    ("2025-10", "MONTH"),

    # ===== TENDAYS =====
    ("2025-10上旬", "TENDAYS"),
    ("2025-10中旬", "TENDAYS"),
    ("2025-10下旬", "TENDAYS"),

    # ===== WEEK =====
    ("2025-W10", "WEEK"),
    ("2025-W31", "WEEK"),
    ("2025-W52", "WEEK"),

    # ===== DAY =====
    ("2025-10-15", "DAY"),
    ("2024-12-31", "DAY"),

    # ===== HOUR =====
    ("2025-10-15 14", "HOUR"),
    ("2025-10-01 00", "HOUR"),

    # ===== SHIFT =====（不降级）
    ("2025-10-15 白班", "SHIFT"),
    ("2025-10-15 夜班", "SHIFT"),

    # ===== 自然语言日期，依赖 LLM 自行解析 =====
    ("今天", "DAY"),
    ("昨天", "DAY"),
    ("本周", "WEEK"),
    ("上周", "WEEK"),
    ("本月", "MONTH"),
    ("上个月", "MONTH"),
    ("今年", "YEAR"),
    ("去年", "YEAR"),

    # ===== 非范围但已经是绝对形式 =====
    ("2025-10-15 05", "HOUR"),
]


async def run_all_tests():
    print("=== Running Time Range Normalizer Tests ===\n")

    for timeString, timeType in TEST_CASES:
        print(f"Input: timeString={timeString}, timeType={timeType}")
        res = await normalize_time_range(timeString, timeType)
        print("Output:", res)
        print("-" * 60)

    print("\n=== All tests done. ===")


if __name__ == "__main__":
    asyncio.run(run_all_tests())
