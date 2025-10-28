# tests/test_v2_full_flow.py
import sys
import os
import asyncio
import logging

# --------------------------
# 临时加入项目根目录到 PYTHONPATH
# --------------------------
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.pipeline import process_message

from tools import formula_api
formula_api.initialize()

# ------------------------------
# Mock 替换 tools.formula_api / platform_api
# ------------------------------
import tools

class MockFormulaAPI:
    def initialize(self):
        self.data_loaded = True
        print("✅ MockFormulaAPI 初始化完成")

    def formula_query_dict(self, indicator_name):
        # 高分公式示例
        return {
            "done": True,
            "exact_matches": [{"FORMULAID": f"{indicator_name}_001", "FORMULANAME": indicator_name}],
            "candidates": [
                {"number": 1, "FORMULAID": f"{indicator_name}_001", "FORMULANAME": indicator_name, "score": 120}
            ]
        }

class MockPlatformAPI:
    async def query_platform(self, formula, timeString=None, timeType=None):
        return {formula: f"{100 + hash(formula)%100} GJ/t", "unit": "GJ/t"}

tools.formula_api = MockFormulaAPI()
tools.platform_api = MockPlatformAPI()

# ------------------------------
# 测试函数
# ------------------------------
async def run_pipeline_test(user_id, message, state=None):
    state = state or {}
    print("===== Pipeline Test =====")
    print(f"User Input: {message}")
    reply, new_state = await process_message(user_id, message, state)
    print("Reply:")
    print(reply)
    print("New State:", new_state)
    print("=========================")
    return new_state

# ------------------------------
# 主函数
# ------------------------------
async def main():
    user_id = "test_user"
    state = {}

    # 第一次查询
    state = await run_pipeline_test(user_id, "查询高炉能耗", state)

    # 第二次查询，带时间
    state = await run_pipeline_test(user_id, "2025-10月的转炉能耗", state)

    # 第三次查询，多个指标
    state = await run_pipeline_test(user_id, "高炉能耗和转炉能耗", state)

# ------------------------------
# 执行
# ------------------------------
if __name__ == "__main__":
    asyncio.run(main())
