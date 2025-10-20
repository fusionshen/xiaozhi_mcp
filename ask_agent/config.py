import os
from datetime import timedelta
from dotenv import load_dotenv

# 加载 .env 环境变量
load_dotenv()

# === 登录相关配置 ===
TENANT_NAME = os.getenv("TENANT_NAME")
APP_KEY = os.getenv("APP_KEY")
APP_SECRET = os.getenv("APP_SECRET")
USER_NAME = os.getenv("USER_NAME")

LOGIN_URL = os.getenv("LOGIN_URL")
QUERY_URL = os.getenv("QUERY_URL")

TOKEN_EXPIRE_DURATION = timedelta(hours=float(os.getenv("TOKEN_EXPIRE_HOURS", 1)))

# 校验
if not all([TENANT_NAME, APP_KEY, APP_SECRET, USER_NAME, LOGIN_URL, QUERY_URL]):
    raise ValueError("❌ 环境变量缺失，请检查 .env 文件配置是否完整。")
