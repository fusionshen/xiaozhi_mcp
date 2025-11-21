import os
for key in ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"]:
    os.environ.pop(key, None)

import asyncio
import time
import logging
from fastapi import FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from core.intent_router import route_intent
from tools import formula_api
from agent_state import get_state, update_state, cleanup_expired_sessions


# ----------------------
# 初始化日志
# ----------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
logger = logging.getLogger(__name__)

app = FastAPI(title="智能能源多意图对话引擎")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True, 
    allow_methods=["*"], 
    allow_headers=["*"]
)

# ----------------------
# 启动事件
# ----------------------
@app.on_event("startup")
async def startup_event():
    """
    在服务启动时执行：
      - 初始化公式数据（同步加载）；
      - 启动清理任务；
    """
    try:
        start = time.time()
        # 只初始化一次，不会重复加载
        formula_api.initialize()
        logger.info(f"✅ formula_api 初始化完成，用时 {time.time() - start:.2f}s")
    except Exception as e:
        logger.exception("❌ 初始化 formula_api 失败: %s", e)

    asyncio.create_task(cleanup_expired_sessions())
    logger.info("🧹 已启动 session 定期清理任务。")

@app.get("/chat")
async def chat_get(
    user_id: str = Query(..., description="用户唯一标识，例如 test1"),
    message: str = Query(..., description="用户输入内容"),
    pretty: bool = Query(False, description="是否返回美化后的回复（默认 false）")
):
    result = await route_intent(user_id, message, pretty)
    return result
