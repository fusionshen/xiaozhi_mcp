import re
import logging
import os
import pickle
from typing import List, Optional
import pandas as pd
import numpy as np
import jieba
import torch
import time

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from rapidfuzz import process, fuzz

from config import (
    EMBEDDING_CACHE_NAME, FORMULA_CSV_NAME, COMBINE_WEIGHT_LIST, DEFAULT_COMBINE_BOOST, ENABLE_TEXT_SCORE_WEIGHT
)

try:
    from sentence_transformers import SentenceTransformer
    HAVE_ST = True
    print(f"✅ sentence-transformers 版本: 5.1.1")
except Exception as e:
    HAVE_ST = False
    print(f"❌ sentence-transformers 导入失败: {e}")

# ================= 日志配置 =================
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("formula-api")

# ================= FastAPI 初始化 =================
app = FastAPI(title="Formula Query API - Jieba + Semantic (weighted hybrid)")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"]
)

# ================= 全局路径配置 =================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(BASE_DIR, ".."))

DATA_DIR = os.path.join(PROJECT_ROOT, "data")
MODELS_DIR = os.path.join(PROJECT_ROOT, "models", "sbert_offline_models")

EMBEDDING_CACHE_PATH = os.path.join(DATA_DIR, EMBEDDING_CACHE_NAME)
FORMULA_CSV_PATH = os.path.join(DATA_DIR, FORMULA_CSV_NAME)

# ---- 离线模型优先路径 ----
OFFLINE_MODEL_PATH = os.path.join(MODELS_DIR, "86741b4e3f5cb7765a600d3a3d55a0f6a6cb443d")

# ---- 在线模型备用 ----
EMBEDDING_MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"

# 环境变量设备控制
ENV_EMBEDDING_DEVICE = os.environ.get("EMBEDDING_DEVICE", "").lower()


# ================= 全局变量 =================
df: Optional[pd.DataFrame] = None
_formulanames_raw: List[str] = []
_formulanames_clean: List[str] = []
_formulanames_tokens: List[str] = []
_embeddings: Optional[np.ndarray] = None
_embedding_model = None
_initialized = False  # ✅ 防止重复初始化


# ===========================================================
# 工具函数
# ===========================================================
def normalize_text(s: str) -> str:
    if s is None:
        return ""
    s = str(s).strip().strip('"').strip("'")
    s = s.replace("#", " ")
    s = re.sub(r"[^\w\u4e00-\u9fff]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def tokens_by_jieba(s: str) -> str:
    if not s:
        return ""
    segs = jieba.cut(s, cut_all=False)
    return " ".join([t for t in segs if t.strip()])


def l2_normalize_matrix(mat: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return mat / norms


def select_embedding_device() -> str:
    """自动选择设备（优先环境变量）"""
    device = "cpu"
    if ENV_EMBEDDING_DEVICE in ["cuda", "mps", "cpu"]:
        device = ENV_EMBEDDING_DEVICE
        logger.info(f"Using embedding device from environment: {device}")
    else:
        if torch.cuda.is_available():
            device = "cuda"
        elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            device = "mps"
        logger.info(f"Auto-selected embedding device: {device}")
    return device


# ===========================
# 1️⃣ apply_combine_weights
# ===========================
def apply_combine_weights(formula_name: str, base_score: float, user_input: str = "") -> float:
    """
    根据 COMBINE_WEIGHT_LIST 动态提升分数：
    - 如果 formula_name 包含某组合的所有 terms
    - 且用户输入没有完全包含该组合
    - 按 weight 提升 base_score
    """
    weighted = float(base_score)
    formula_text = str(formula_name or "")
    user_text = str(user_input or "")

    if not ENABLE_TEXT_SCORE_WEIGHT or base_score <= 0:
        return weighted

    # 按 weight 降序遍历组合，保证高权重优先
    combos = sorted(COMBINE_WEIGHT_LIST, key=lambda c: c.get("weight", 0), reverse=True)

    for combo in combos:
        terms = combo.get("terms", [])
        weight = float(combo.get("weight", 0.0))
        if not terms:
            continue

        # formula_name 是否包含该组合所有 term
        if all(term in formula_text for term in terms):
            # 用户输入是否已包含该组合
            if not all(term in user_text for term in terms):
                # 加权提升
                weighted *= (1.0 + weight)

    return weighted


# ===========================================================
# 初始化函数（核心改动）
# ===========================================================
def initialize():
    """初始化公式数据与嵌入，只执行一次"""
    global df, _formulanames_raw, _formulanames_clean, _formulanames_tokens
    global _embedding_model, _embeddings, HAVE_ST, _initialized

    # ✅ 避免重复加载（从 main.py 导入不会执行第二次）
    if _initialized:
        logger.info("✅ formula_api 已初始化，跳过重复加载。")
        return

    start_time = time.time()
    logger.info("🔄 正在初始化公式数据（full load）...")

    # ---- 加载 CSV ----
    if not os.path.exists(FORMULA_CSV_PATH):
        raise RuntimeError(f"⚠️ 找不到公式数据文件: {os.path.abspath(FORMULA_CSV_PATH)}")

    try:
        df = pd.read_csv(FORMULA_CSV_PATH, dtype=str, quoting=3, engine="python", on_bad_lines="skip")
        df.columns = [c.strip().replace('"', '') for c in df.columns]
        if not {"FORMULAID", "FORMULANAME"}.issubset(df.columns):
            raise RuntimeError(f"CSV 缺少必要列: {list(df.columns)}")
        df = df[["FORMULAID", "FORMULANAME"]].fillna("")
        _formulanames_raw = df["FORMULANAME"].astype(str).tolist()
        _formulanames_clean = [normalize_text(s) for s in _formulanames_raw]
        _formulanames_tokens = [tokens_by_jieba(s) for s in _formulanames_clean]
        _ = list(jieba.cut("测试"))  # 触发 jieba 初始化
        logger.info(f"✅ Loaded {len(df)} formulas. Tokenization ready.")
    except Exception as e:
        logger.exception("❌ Failed to load CSV")
        raise RuntimeError(f"Failed to load CSV: {e}")
    
    print(f"HAVE_ST : {HAVE_ST}")
    # ---- 尝试加载嵌入模型 ----
    if HAVE_ST:
        device = select_embedding_device()
        try:
            # ✅ 优先加载本地模型
            print(f"OFFLINE_MODEL_PATH:{OFFLINE_MODEL_PATH}") 
            if os.path.exists(OFFLINE_MODEL_PATH):
                logger.info(f"🧩 尝试加载本地模型: {OFFLINE_MODEL_PATH}")
                _embedding_model = SentenceTransformer(OFFLINE_MODEL_PATH, device=device)
                logger.info("✅ 已成功加载离线模型。")
            else:
                logger.warning("⚠️ 离线模型未找到，使用默认在线模型。")
                _embedding_model = SentenceTransformer(EMBEDDING_MODEL_NAME, device=device)
                logger.info("✅ 已加载在线模型。")
        except Exception as e:
            logger.warning(f"⚠️ 本地模型加载失败，回退到在线模型。错误: {e}")
            _embedding_model = SentenceTransformer(EMBEDDING_MODEL_NAME, device=device)
            logger.info("✅ 已加载在线模型。")

        # ---- 加载或生成嵌入缓存 ----
        if os.path.exists(EMBEDDING_CACHE_PATH):
            with open(EMBEDDING_CACHE_PATH, "rb") as f:
                cached_data = pickle.load(f)
            if cached_data.get("formula_count") == len(_formulanames_raw):
                _embeddings = cached_data["embeddings"]
                logger.info(f"✅ Loaded embeddings from cache ({_embeddings.shape})")
            else:
                logger.warning("⚠️ Embedding cache formula count mismatch, recalculating...")
                _embeddings = _compute_and_cache_embeddings()
        else:
            _embeddings = _compute_and_cache_embeddings()
    else:
        logger.warning("⚠️ sentence-transformers not installed — semantic mode DISABLED.")
        _embedding_model = None
        _embeddings = None

    _initialized = True
    logger.info(f"✅ 初始化完成，用时 {time.time() - start_time:.2f}s")


def _compute_and_cache_embeddings():
    """重新计算并缓存嵌入"""
    logger.info("🔄 Computing new embeddings...")
    emb_list = _embedding_model.encode(
        _formulanames_raw, batch_size=64, show_progress_bar=True, convert_to_numpy=True
    )
    embeddings = l2_normalize_matrix(np.asarray(emb_list, dtype=np.float32))
    with open(EMBEDDING_CACHE_PATH, "wb") as f:
        pickle.dump({"formula_count": len(_formulanames_raw), "embeddings": embeddings}, f)
    logger.info(f"✅ Cached new embeddings ({embeddings.shape})")
    return embeddings


# ===========================
# 2️⃣ fuzzy_search
# ===========================
def fuzzy_search(user_input: str, topn: int = 5):
    key_clean = normalize_text(user_input)
    key_tokens = tokens_by_jieba(key_clean)
    if not key_tokens:
        return []

    results = process.extract(key_tokens, _formulanames_tokens, scorer=fuzz.token_set_ratio, limit=topn*3)
    candidates = []
    for rank, (match_text, score, match_index) in enumerate(results, start=1):
        row = df.iloc[match_index]
        clean_name = str(row["FORMULANAME"]).strip().strip('"').strip("'")
        base_score = float(score) / 100.0  # 归一化
        final_score = apply_combine_weights(clean_name, base_score, user_input)
        candidates.append({
            "number": rank,
            "FORMULAID": row["FORMULAID"],
            "FORMULANAME": clean_name,
            "score": round(final_score, 4),
            "match_kind": "fuzzy_token_set"
        })
    return sorted(candidates, key=lambda x: x["score"], reverse=True)[:topn]


# ===========================
# 3️⃣ semantic_search
# ===========================
def semantic_search(user_input: str, topn: int = 5):
    if _embedding_model is None or _embeddings is None:
        return []

    vec = _embedding_model.encode([user_input], convert_to_numpy=True).astype(np.float32)
    vec = vec / (np.linalg.norm(vec, axis=1, keepdims=True) + 1e-12)
    sims = np.dot(_embeddings, vec[0])  # cosine similarity [-1,1]

    candidates = []
    for idx in np.argsort(-sims)[:topn*3]:
        row = df.iloc[idx]
        clean_name = str(row["FORMULANAME"]).strip().strip('"').strip("'")
        base_score = (float(sims[idx]) + 1.0) / 2.0  # [-1,1] -> [0,1]
        final_score = apply_combine_weights(clean_name, base_score, user_input)
        candidates.append({
            "number": len(candidates)+1,
            "FORMULAID": row["FORMULAID"],
            "FORMULANAME": clean_name,
            "score": round(final_score, 4),
            "match_kind": "semantic_cosine"
        })
    return sorted(candidates, key=lambda x: x["score"], reverse=True)[:topn]



# ===========================
# 4️⃣ hybrid_search
# ===========================
def hybrid_search(user_input: str, topn: int = 5, fuzzy_weight: float = 0.4, semantic_weight: float = 0.6):
    fuzzy_candidates = fuzzy_search(user_input, topn=topn*3)
    if not HAVE_ST or _embeddings is None:
        return fuzzy_candidates[:topn]

    vec = _embedding_model.encode([user_input], convert_to_numpy=True).astype(np.float32)
    vec = vec / (np.linalg.norm(vec, axis=1, keepdims=True) + 1e-12)
    sims = np.dot(_embeddings, vec[0])  # [-1,1]

    merged = []
    for c in fuzzy_candidates:
        idx = int(df.index[df["FORMULAID"] == c["FORMULAID"]][0])
        semantic_score = (float(sims[idx]) + 1.0) / 2.0  # [-1,1] -> [0,1]
        fuzzy_score = float(c["score"])  # 已归一化
        combined_score = fuzzy_weight * fuzzy_score + semantic_weight * semantic_score
        clean_name = str(df.iloc[idx]["FORMULANAME"]).strip().strip('"').strip("'")
        final_score = apply_combine_weights(clean_name, combined_score, user_input)
        merged.append((final_score, fuzzy_score, semantic_score, idx))

    merged.sort(key=lambda x: x[0], reverse=True)

    candidates = []
    for rank, (final_score, fuzzy_score, semantic_score, idx) in enumerate(merged[:topn], start=1):
        row = df.iloc[idx]
        candidates.append({
            "number": rank,
            "FORMULAID": row["FORMULAID"],
            "FORMULANAME": str(row["FORMULANAME"]).strip().strip('"').strip("'"),
            "score": round(float(final_score), 4),
            "fuzzy_score": round(float(fuzzy_score), 4),
            "semantic_score": round(float(semantic_score), 4),
            "match_kind": "hybrid"
        })

    return candidates

def hierarchical_exact_match(user_input: str, df, combine_weight_list):
    user_input = user_input.strip()

    # 按 weight 降序，保证 weight 高的优先
    combos = sorted(combine_weight_list, key=lambda c: c["weight"], reverse=True)

    for item in combos:
        terms = item["terms"]  # 可动态多级，例如 ["实绩","报出值","地区A"]

        # 找用户输入命中 terms 的最长前缀长度
        prefix_len = 0
        for i, term in enumerate(terms):
            if term in user_input:
                prefix_len += 1
            else:
                break

        # 剩余层级需要拼接
        suffix = "".join(terms[prefix_len:])
        candidate = user_input + suffix if suffix else user_input

        # 避免重复拼接，直接查找精确匹配
        exact = df[df["FORMULANAME"] == candidate]
        if not exact.empty:
            row = exact.iloc[0]
            return {
                "FORMULAID": row["FORMULAID"],
                "FORMULANAME": row["FORMULANAME"],
            }

    return None


# ===========================================================
# API 接口
# ===========================================================
@app.get("/formula_query")
def formula_query(
    user_input: str = Query(..., description="User input: keyword or exact formula name"),
    topn: int = Query(5, ge=1, le=50, description="Number of candidates to return"),
    method: str = Query("hybrid", description="Search method: fuzzy | semantic | hybrid")
):
    return JSONResponse(content=formula_query_dict(user_input, topn, method))


# ===========================================================
# formula_query_dict 改写版
# ===========================================================
def formula_query_dict(user_input: str, topn: int = 5, method: str = "hybrid") -> dict:
    """
    返回候选公式的 dict，规则：
    1️⃣ 精确匹配优先（FORMULANAME 完全等于输入或 normalize_text 后相等）
    2️⃣ 若无精确匹配，根据 method 调用 fuzzy / semantic / hybrid
    3️⃣ 分数归一化 [0,1]，应用组合权重
    4️⃣ 返回 topn 结果
    """
    user_input = str(user_input or "").strip().strip('"').strip("'")
    if not user_input:
        return {"done": False, "message": "Empty input.", "candidates": []}

    # 0️⃣ 层级精确查找
    hier = hierarchical_exact_match(user_input, df, COMBINE_WEIGHT_LIST)
    if hier:
        logger.info(f"✅ Hierarchical exact match: {hier['FORMULANAME']}")
        return {
            "done": True,
            "message": f"Hierarchical exact match: {hier['FORMULANAME']}",
            "exact_matches": [hier]
        }

    # ===== 1️⃣ 精确匹配 =====
    exact = df[df["FORMULANAME"] == user_input]
    if exact.empty:
        # 尝试 normalize_text 后匹配
        clean_input = normalize_text(user_input)
        matches_idx = [i for i, v in enumerate(_formulanames_clean) if v == clean_input]
        if matches_idx:
            exact = pd.DataFrame([df.iloc[matches_idx[0]]])

    if not exact.empty:
        exact_matches = exact[["FORMULAID", "FORMULANAME"]].to_dict(orient="records")
        for item in exact_matches:
            item["FORMULANAME"] = str(item["FORMULANAME"]).strip()
        return {
            "done": True,
            "message": f"Exact match found: {exact_matches[0]['FORMULANAME']}",
            "exact_matches": exact_matches,
            "candidates": exact_matches
        }

    # ===== 2️⃣ 模糊 / 语义 / 混合搜索 =====
    method_str = str(method).lower()
    candidates = []
    try:
        if method_str == "fuzzy":
            candidates = fuzzy_search(user_input, topn=topn)
        elif method_str == "semantic":
            candidates = semantic_search(user_input, topn=topn)
        elif method_str == "hybrid":
            candidates = hybrid_search(user_input, topn=topn)
        else:
            return {"done": False, "message": f"Unknown method: {method_str}", "candidates": []}
    except Exception as e:
        logger.exception("❌ Search error")
        return {"done": False, "message": f"Search error: {e}", "candidates": []}

    if not candidates:
        return {"done": False, "message": "No matches found.", "candidates": []}

    # ===== 3️⃣ 排序 + 分数归一化 =====
    # 分数已经在 fuzzy / semantic / hybrid 中归一化 + 应用组合权重
    candidates_sorted = sorted(candidates, key=lambda x: x["score"], reverse=True)[:topn]

    return {
        "done": False,
        "message": f"{len(candidates_sorted)} candidates returned.",
        "candidates": candidates_sorted
    }
    


@app.on_event("startup")
def load_csv_and_prepare():
    """FastAPI 启动时自动调用"""
    initialize()

# ===========================================================
# 独立运行支持（python formula_api.py）
# ===========================================================
if __name__ == "__main__":
    initialize()
    print("✅ formula_api 独立运行模式启动完成。")
