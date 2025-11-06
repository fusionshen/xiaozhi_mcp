"""
core 包 - V2 版本的智能体核心模块。

功能：
- context_graph: 上下文语义图谱管理
- pipeline: 输入解析与多指标查询主流程
- energy_query_runner: 能源智能问数
- utils: 工具函数与通用方法
"""

from .context_graph import ContextGraph
from .pipeline import process_message
from .energy_query_runner import run_energy_query
from .utils import now_str

__all__ = ["ContextGraph", "process_message", "run_energy_query", "now_str"]
