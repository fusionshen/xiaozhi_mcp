# config/config.py
import os
import json
from datetime import timedelta
from dotenv import load_dotenv
from pathlib import Path
import logging

logger = logging.getLogger("config")
if not logger.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )


# --- 1. 根目录 ---
ROOT_DIR = Path(__file__).resolve().parents[1]

# --- 2. config 目录 ---
CONFIG_DIR = Path(__file__).resolve().parent

# --- 3. 加载 .env ---
ENV_PATH = ROOT_DIR / ".env"
load_dotenv(ENV_PATH)

# === 登录相关配置 ===
TENANT_NAME = os.getenv("TENANT_NAME")
APP_KEY = os.getenv("APP_KEY")
APP_SECRET = os.getenv("APP_SECRET")
USER_NAME = os.getenv("USER_NAME")

LOGIN_URL = os.getenv("LOGIN_URL")
QUERY_URL = os.getenv("QUERY_URL")
RANGE_QUERY_URL = os.getenv("RANGE_QUERY_URL")
TOKEN_EXPIRE_DURATION = timedelta(hours=float(os.getenv("TOKEN_EXPIRE_HOURS", 1)))

# === 模型配置 ===
LLM_CHAIN = os.getenv("LLM_CHAIN", "api,remote,local").lower().split(",")
LLM_CHAIN = [x.strip() for x in LLM_CHAIN if x.strip()]
logger.info(f"🔧 LLM_CHAIN={LLM_CHAIN}")

LLM_API_URL = os.getenv("LLM_API_URL") 
LLM_API_KEY = os.getenv("LLM_API_KEY") 
LLM_API_TIMEOUT = os.getenv("LLM_API_TIMEOUT") 
REMOTE_OLLAMA_URL = os.getenv("REMOTE_OLLAMA_URL")  # ← 修改为你的远程 Ollama 地址
REMOTE_MODEL = os.getenv("REMOTE_MODEL")
LOCAL_MODEL = os.getenv("LOCAL_MODEL")

EMBEDDING_CACHE_NAME = os.getenv("EMBEDDING_CACHE_NAME")
FORMULA_CSV_NAME = os.getenv("FORMULA_CSV_NAME")

TEXT_SCORE_WEIGHT_FILE = os.getenv("TEXT_SCORE_WEIGHT_FILE")
ENABLE_TEXT_SCORE_WEIGHT = os.getenv("ENABLE_TEXT_SCORE_WEIGHT") in ["True", "true", "1"]

ENABLE_GRAGH_DEBUG_JSON = os.getenv("ENABLE_GRAGH_DEBUG_JSON") in ["True", "true", "1"]

ENABLE_REMOVE_SYMBOLS = os.getenv("ENABLE_REMOVE_SYMBOLS") in ["True", "true", "1"]

with open(CONFIG_DIR / TEXT_SCORE_WEIGHT_FILE, "r", encoding="utf-8") as f:
    raw_cfg = json.load(f)

# 组合权重：list → 方便遍历
COMBINE_WEIGHT_LIST = raw_cfg.get("combines", [])

# 默认提升
DEFAULT_COMBINE_BOOST = raw_cfg.get("default_boost", 0.0)

# === 服务监听配置 ===
HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", 8000))

# 校验关键配置
required_vars = [
    TENANT_NAME, APP_KEY, APP_SECRET, USER_NAME,
    LOGIN_URL, QUERY_URL, RANGE_QUERY_URL, LLM_CHAIN,
    EMBEDDING_CACHE_NAME, FORMULA_CSV_NAME, TEXT_SCORE_WEIGHT_FILE
]
if not all(required_vars):
    raise ValueError("❌ 环境变量缺失，请检查 .env 文件")
