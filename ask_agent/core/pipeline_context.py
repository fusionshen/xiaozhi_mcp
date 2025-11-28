# core/pipeline_context.py
"""
统一管理各用户的 ContextGraph 对象，内存优先 + 异步持久化
支持：
1. pickle 压缩文件用于快速恢复
2. JSON 文件用于调试和可读
"""

import os
import asyncio
import pickle
import gzip
import json
from typing import Dict
from core.context_graph import ContextGraph
import logging
import config

logger = logging.getLogger("pipeline_context")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

# 内存缓存：用户 ID -> ContextGraph
_graph_store: Dict[str, ContextGraph] = {}

# 图谱存储目录
GRAPH_DIR = os.path.join(os.path.dirname(__file__), "../data/graphs")
os.makedirs(GRAPH_DIR, exist_ok=True)

# ----------------------
# 工具函数
# ----------------------
def _get_graph_paths(user_id: str):
    safe_user = user_id.replace("/", "_")
    pkl_path = os.path.join(GRAPH_DIR, f"{safe_user}.pkl.gz")
    json_path = os.path.join(GRAPH_DIR, f"{safe_user}.json")
    return pkl_path, json_path

async def save_graph_async(user_id: str, graph: ContextGraph):
    pkl_path, json_path = _get_graph_paths(user_id)
    try:
        loop = asyncio.get_event_loop()
        # 保存 pickle 压缩文件
        await loop.run_in_executor(
            None, lambda: gzip.open(pkl_path, "wb").write(pickle.dumps(graph))
        )
        logger.info(f"💾 异步保存用户图谱 {user_id} -> {pkl_path}")
    except Exception as e:
        logger.exception(f"⚠️ 保存用户 {user_id} 图谱失败: {e}")

    if config.ENABLE_GRAGH_DEBUG_JSON:
        try:
            state = graph.to_state()  # 确保 ContextGraph 有 to_state() 方法
            await loop.run_in_executor(
                None,
                lambda: json.dump(state, open(json_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
            )
            logger.info(f"📝 保存 JSON 调试文件 {user_id} -> {json_path}")
        except Exception as e:
            logger.exception(f"⚠️ 保存用户 {user_id} JSON 图谱失败: {e}")

def load_graph_from_file(user_id: str) -> ContextGraph | None:
    pkl_path, _ = _get_graph_paths(user_id)
    if not os.path.exists(pkl_path):
        return None
    try:
        with gzip.open(pkl_path, "rb") as f:
            graph = pickle.load(f)
        logger.info(f"📂 加载用户图谱 {user_id} <- {pkl_path}")
        return graph
    except Exception as e:
        logger.exception(f"⚠️ 加载用户 {user_id} 图谱失败: {e}")
        return None

# ----------------------
# 接口
# ----------------------
def get_graph(user_id: str) -> ContextGraph:
    """获取用户图谱，如果内存没有就尝试从文件加载"""
    graph = _graph_store.get(user_id)
    if not graph:
        graph = load_graph_from_file(user_id)
        if not graph:
            graph = ContextGraph()
        _graph_store[user_id] = graph
    return graph

def set_graph(user_id: str, graph: ContextGraph) -> None:
    """更新内存，并异步保存到磁盘（pickle + JSON）"""
    _graph_store[user_id] = graph
    asyncio.create_task(save_graph_async(user_id, graph))

def remove_graph(user_id: str) -> None:
    """删除用户图谱（内存 + 文件）"""
    _graph_store.pop(user_id, None)
    pkl_path, json_path = _get_graph_paths(user_id)
    for path in [pkl_path, json_path]:
        if os.path.exists(path):
            try:
                os.remove(path)
                logger.info(f"🗑 删除用户图谱文件 {user_id} -> {path}")
            except Exception as e:
                logger.exception(f"⚠️ 删除用户图谱文件失败 {user_id}: {e}")

def all_graphs() -> Dict[str, ContextGraph]:
    """获取所有用户内存图谱"""
    return _graph_store

# ----------------------
# 启动时加载所有已有图谱
# ----------------------
async def load_all_graphs():
    files = [f for f in os.listdir(GRAPH_DIR) if f.endswith(".pkl.gz")]
    for f in files:
        user_id = f[:-7]  # 去掉 ".pkl.gz"
        g = load_graph_from_file(user_id)
        if g:
            _graph_store[user_id] = g
    logger.info(f"✅ 已加载 {len(_graph_store)} 个用户图谱")

# ----------------------
# 可选定时持久化任务
# ----------------------
async def persist_all_graphs_task(interval_sec: int = 300):
    while True:
        logger.info(f"⏳ 开始批量持久化所有用户图谱...")
        for user_id, graph in _graph_store.items():
            await save_graph_async(user_id, graph)
        await asyncio.sleep(interval_sec)
