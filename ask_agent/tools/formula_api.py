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
import asyncio

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from rapidfuzz import process, fuzz

try:
    from sentence_transformers import SentenceTransformer
    HAVE_ST = True
except Exception:
    HAVE_ST = False

# ================= 日志配置 =================
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("formula-api")

# ================= FastAPI 初始化 =================
app = FastAPI(title="Formula Query API - Jieba + Semantic (weighted hybrid)")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"]
)

# ================= 全局配置 =================
# 获取当前文件所在目录（而不是工作目录）
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 项目根目录（假设 tools 与 data 同级）
PROJECT_ROOT = os.path.abspath(os.path.join(BASE_DIR, ".."))

# 拼出 data 路径
EMBEDDING_CACHE_PATH = os.path.join(PROJECT_ROOT, "data", "formula_embeddings.pkl")
FORMULA_CSV_PATH = os.path.join(PROJECT_ROOT, "data", "FORMULAINFO_202503121558.csv")

CSV_PATH = os.environ.get("FORMULA_CSV", FORMULA_CSV_PATH)
EMBEDDING_MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"
ENV_EMBEDDING_DEVICE = os.environ.get("EMBEDDING_DEVICE", "").lower()

TEXT_SCORE_WEIGHT_MAP = {
    "实绩": 0.08,
    "报出": 0.01,
    "计划": -0.01,
    "累计": -0.02,
}
ENABLE_TEXT_SCORE_WEIGHT = True

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


def apply_text_weights(formula_name: str, base_score: float) -> float:
    if not ENABLE_TEXT_SCORE_WEIGHT or base_score <= 0:
        return base_score
    weighted_score = base_score
    for key, w in TEXT_SCORE_WEIGHT_MAP.items():
        if key in formula_name:
            weighted_score *= (1 + w)
    return weighted_score


# ===========================================================
# 初始化函数（改为单例式）
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
    if not os.path.exists(CSV_PATH):
        raise RuntimeError(f"⚠️ 找不到公式数据文件: {os.path.abspath(CSV_PATH)}")

    try:
        try:
            df = pd.read_csv(CSV_PATH, dtype=str, quoting=3, engine="python", on_bad_lines="skip")
        except Exception:
            df = pd.read_csv(CSV_PATH, sep="\t", dtype=str, quoting=3, engine="python", on_bad_lines="skip")
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

    # ---- 加载 / 计算 embeddings ----
    if HAVE_ST:
        device = select_embedding_device()
        try:
            _embedding_model = SentenceTransformer(EMBEDDING_MODEL_NAME, device=device)
            if os.path.exists(EMBEDDING_CACHE_PATH):
                with open(EMBEDDING_CACHE_PATH, "rb") as f:
                    cached_data = pickle.load(f)
                if cached_data.get("formula_count") == len(_formulanames_raw):
                    _embeddings = cached_data["embeddings"]
                    logger.info(f"✅ Loaded embeddings from cache ({_embeddings.shape})")
                else:
                    logger.warning("⚠️ Embedding cache formula count mismatch, recalculating...")
                    emb_list = _embedding_model.encode(
                        _formulanames_raw, batch_size=64, show_progress_bar=True, convert_to_numpy=True
                    )
                    _embeddings = l2_normalize_matrix(np.asarray(emb_list, dtype=np.float32))
                    with open(EMBEDDING_CACHE_PATH, "wb") as f:
                        pickle.dump({"formula_count": len(_formulanames_raw), "embeddings": _embeddings}, f)
                    logger.info(f"✅ Recomputed and cached embeddings ({_embeddings.shape})")
            else:
                emb_list = _embedding_model.encode(
                    _formulanames_raw, batch_size=64, show_progress_bar=True, convert_to_numpy=True
                )
                _embeddings = l2_normalize_matrix(np.asarray(emb_list, dtype=np.float32))
                with open(EMBEDDING_CACHE_PATH, "wb") as f:
                    pickle.dump({"formula_count": len(_formulanames_raw), "embeddings": _embeddings}, f)
                logger.info(f"✅ Computed and cached embeddings ({_embeddings.shape})")
        except Exception as e:
            logger.exception("❌ Failed to load or compute embeddings.")
            HAVE_ST = False
            _embedding_model = None
            _embeddings = None
    else:
        logger.warning("⚠️ sentence-transformers not installed — semantic mode DISABLED.")

    _initialized = True
    logger.info(f"✅ 初始化完成，用时 {time.time() - start_time:.2f}s")

def get_embedding_model():
    """懒加载 embeddings"""
    global _embedding_model, _embeddings, HAVE_ST
    if _embedding_model is not None:
        return _embedding_model
    if not HAVE_ST:
        raise RuntimeError("Semantic mode not available.")
    device = select_embedding_device()
    _embedding_model = SentenceTransformer(EMBEDDING_MODEL_NAME, device=device)
    if os.path.exists(EMBEDDING_CACHE_PATH):
        with open(EMBEDDING_CACHE_PATH, "rb") as f:
            cached_data = pickle.load(f)
        _embeddings = cached_data["embeddings"]
    else:
        emb_list = _embedding_model.encode(_formulanames_raw, batch_size=64, show_progress_bar=True, convert_to_numpy=True)
        _embeddings = l2_normalize_matrix(np.asarray(emb_list, dtype=np.float32))
        with open(EMBEDDING_CACHE_PATH, "wb") as f:
            pickle.dump({"formula_count": len(_formulanames_raw), "embeddings": _embeddings}, f)
    return _embedding_model

# ===========================================================
# 搜索函数（未改动）
# ===========================================================
def fuzzy_search(user_input: str, topn: int = 5):
    key_clean = normalize_text(user_input)
    key_tokens = tokens_by_jieba(key_clean)
    if not key_tokens:
        return []

    results = process.extract(key_tokens, _formulanames_tokens, scorer=fuzz.token_set_ratio, limit=topn * 3)
    candidates = []
    for rank, (match_text, score, match_index) in enumerate(results, start=1):
        row = df.iloc[match_index]
        clean_name = str(row["FORMULANAME"]).strip().strip('"').strip("'")
        final_score = apply_text_weights(clean_name, float(score))
        candidates.append({
            "number": rank,
            "FORMULAID": row["FORMULAID"],
            "FORMULANAME": row["FORMULANAME"],
            "score": round(final_score, 4),
            "match_kind": "fuzzy_token_set"
        })
    return sorted(candidates, key=lambda x: x["score"], reverse=True)[:topn]

def semantic_search(user_input: str, topn: int = 5):
    model = get_embedding_model()
    vec = model.encode([user_input], convert_to_numpy=True).astype(np.float32)
    vec = vec / (np.linalg.norm(vec, axis=1, keepdims=True) + 1e-12)
    sims = np.dot(_embeddings, vec[0])
    top_idx = np.argsort(-sims)[:topn * 3]
    candidates = []
    for rank, idx in enumerate(top_idx, start=1):
        row = df.iloc[int(idx)]
        clean_name = str(row["FORMULANAME"]).strip().strip('"').strip("'")
        base_score = float(sims[idx]) * 100.0
        final_score = apply_text_weights(clean_name, base_score)
        candidates.append({
            "number": rank,
            "FORMULAID": row["FORMULAID"],
            "FORMULANAME": clean_name,
            "score": round(final_score, 4),
            "match_kind": "semantic_cosine"
        })
    return sorted(candidates, key=lambda x: x["score"], reverse=True)[:topn]

def hybrid_search(user_input: str, topn: int = 5, fuzzy_weight: float = 0.4, semantic_weight: float = 0.6):
    fuzzy_candidates = fuzzy_search(user_input, topn=topn * 3)
    if not HAVE_ST or _embeddings is None:
        return fuzzy_candidates[:topn]

    model = get_embedding_model()
    vec = model.encode([user_input], convert_to_numpy=True).astype(np.float32)
    vec = vec / (np.linalg.norm(vec, axis=1, keepdims=True) + 1e-12)
    sims = np.dot(_embeddings, vec[0]) * 100.0

    merged = []
    for c in fuzzy_candidates:
        fid = c["FORMULAID"]
        matched_rows = df.index[df["FORMULAID"] == fid].tolist()
        if not matched_rows:
            continue
        idx = int(matched_rows[0])
        semantic_score = float(sims[idx])
        fuzzy_score = float(c["score"])
        if fuzzy_score > 95:
            fuzzy_weight, semantic_weight = 0.4, 0.6
        clean_name = str(df.iloc[idx]["FORMULANAME"]).strip().strip('"').strip("'")
        final_score = fuzzy_weight * fuzzy_score + semantic_weight * semantic_score
        final_score = apply_text_weights(clean_name, final_score)
        merged.append((final_score, fuzzy_score, semantic_score, idx))

    merged.sort(key=lambda x: x[0], reverse=True)
    candidates = []
    for rank, (final_score, fuzzy_score, semantic_score, idx) in enumerate(merged[:topn], start=1):
        row = df.iloc[idx]
        clean_name = str(row["FORMULANAME"]).strip().strip('"').strip("'")
        candidates.append({
            "number": rank,
            "FORMULAID": row["FORMULAID"],
            "FORMULANAME": clean_name,
            "score": round(float(final_score), 4),
            "fuzzy_score": round(float(fuzzy_score), 4),
            "semantic_score": round(float(semantic_score), 4),
            "match_kind": "hybrid"
        })
    return candidates

# ===========================================================
# API 接口
# ===========================================================
@app.get("/formula_query")
def formula_query(
    user_input: str = Query(..., description="User input: keyword or exact formula name"),
    topn: int = Query(5, ge=1, le=50, description="Number of candidates to return"),
    method: str = Query("hybrid", description="Search method: fuzzy | semantic | hybrid")
):
    user_input = user_input.strip().strip('"').strip("'")
    if not user_input:
        return JSONResponse(content={"done": False, "message": "Empty input."})

    # 精确匹配
    exact = df[df["FORMULANAME"] == user_input]
    if exact.empty:
        clean_input = normalize_text(user_input)
        matches_idx = [i for i, v in enumerate(_formulanames_clean) if v == clean_input]
        if matches_idx:
            exact = pd.DataFrame([df.iloc[matches_idx[0]]])
    if not exact.empty:
        exact_matches = exact[["FORMULAID", "FORMULANAME"]].to_dict(orient="records")
        for item in exact_matches:
            item["FORMULANAME"] = str(item["FORMULANAME"]).strip().strip('"').strip("'")
        return JSONResponse(content={
            "done": True,
            "message": f"Exact match found: {exact_matches[0]['FORMULANAME']}",
            "exact_matches": exact_matches
        })

    # 模糊 / 语义 / 混合
    try:
        method = method.lower()
        if method == "fuzzy":
            candidates = fuzzy_search(user_input, topn=topn)
        elif method == "semantic":
            candidates = semantic_search(user_input, topn=topn)
        elif method == "hybrid":
            candidates = hybrid_search(user_input, topn=topn)
        else:
            return JSONResponse(content={"done": False, "message": f"Unknown method: {method}"})
    except Exception as e:
        logger.exception("❌ Search error")
        return JSONResponse(content={"done": False, "message": f"Search error: {e}", "candidates": []})

    if not candidates:
        return JSONResponse(content={"done": False, "message": "No matches found.", "candidates": []})

    msg_lines = ["Multiple candidates found, choose by number:"]
    for c in candidates:
        if c.get("match_kind") == "hybrid":
            msg_lines.append(f"{c['number']}) {c['FORMULANAME']} (final {c['score']}, fuzzy {c['fuzzy_score']}, semantic {c['semantic_score']})")
        else:
            msg_lines.append(f"{c['number']}) {c['FORMULANAME']} (score {c['score']})")

    return JSONResponse(content={
        "done": False,
        "message": "\n".join(msg_lines),
        "candidates": candidates
    })

# 保留原 startup
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
