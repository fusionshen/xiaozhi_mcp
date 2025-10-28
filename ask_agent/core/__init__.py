"""
core 包 - V2 版本的智能体核心模块。

功能：
- context_graph: 上下文语义图谱管理
- pipeline: 输入解析与多指标查询主流程
- query_engine: 并行调用数据接口并聚合结果
- utils: 工具函数与通用方法
"""

from .context_graph import ContextGraph
from .pipeline import process_message
from .query_engine import query_multiple_indicators
from .utils import now_str

__all__ = ["ContextGraph", "process_message", "query_multiple_indicators", "now_str"]
