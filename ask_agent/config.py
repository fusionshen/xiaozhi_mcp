import os
import json
from datetime import timedelta
from dotenv import load_dotenv

# 加载 .env
load_dotenv()

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
REMOTE_OLLAMA_URL = os.getenv("REMOTE_OLLAMA_URL")  # ← 修改为你的远程 Ollama 地址
REMOTE_MODEL = os.getenv("REMOTE_MODEL")
LOCAL_MODEL = os.getenv("LOCAL_MODEL")

EMBEDDING_CACHE_NAME = os.getenv("EMBEDDING_CACHE_NAME")
FORMULA_CSV_NAME = os.getenv("FORMULA_CSV_NAME")

TEXT_SCORE_WEIGHT_FILE = os.getenv("TEXT_SCORE_WEIGHT_FILE")
ENABLE_TEXT_SCORE_WEIGHT = os.getenv("ENABLE_TEXT_SCORE_WEIGHT") in ["True", "true", "1"]

with open(TEXT_SCORE_WEIGHT_FILE, "r", encoding="utf-8") as f:
    TEXT_SCORE_WEIGHT_MAP = json.load(f)

# === 服务监听配置 ===
HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", 8000))

# 校验关键配置
required_vars = [
    TENANT_NAME, APP_KEY, APP_SECRET, USER_NAME,
    LOGIN_URL, QUERY_URL, RANGE_QUERY_URL,
    REMOTE_OLLAMA_URL, REMOTE_MODEL, LOCAL_MODEL,
    EMBEDDING_CACHE_NAME, FORMULA_CSV_NAME, TEXT_SCORE_WEIGHT_FILE
]
if not all(required_vars):
    raise ValueError("❌ 环境变量缺失，请检查 .env 文件")
