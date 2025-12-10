import os
for key in ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"]:
    os.environ.pop(key, None)

import asyncio
import time
import logging
from fastapi import FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.application.intent_router import route_intent
from app.domains import energy as energy_domain
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import uvicorn
import config # 导入配置
from app import core

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
# mount images folder so /images/<filename> 能直接被前端访问
images_dir = os.path.join(os.path.dirname(__file__), "data", "images")
# 如果 main.py 不在项目根，请根据实际路径调整 images_dir
if not os.path.exists(images_dir):
    os.makedirs(images_dir, exist_ok=True)
# ----------------------
# 静态目录必须在这里 mount！
# ----------------------
app.mount("/images", StaticFiles(directory=images_dir), name="images")
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
        energy_domain.formula_api.initialize()
        logger.info(f"✅ formula_api 初始化完成，用时 {time.time() - start:.2f}s")
    except Exception as e:
        logger.exception("❌ 初始化 formula_api 失败: %s", e)

    # asyncio.run(core.load_all_graphs())
    # 可选：启动后台定时持久化
    asyncio.create_task(core.persist_all_graphs_task(300))
    logger.info("🧹 已启动 graph 定期持久任务。")

@app.get("/chat")
async def chat_get(
    user_id: str = Query(..., description="用户唯一标识，例如 test1"),
    message: str = Query(..., description="用户输入内容"),
    pretty: bool = Query(False, description="是否返回美化后的回复（默认 false）")
):
    result = await route_intent(user_id, message, pretty)
    return result

# 检查接口（非必须，StaticFiles 已能直接提供文件）
@app.get("/image/{filename}")
async def get_image(filename: str):
    """
    可选的直接文件访问接口，返回 FileResponse。
    前端也可直接访问 /images/{filename}。
    """
    path = os.path.join(images_dir, filename)
    if not os.path.exists(path):
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(path, media_type="image/png")

if __name__ == "__main__":
    # 用配置文件里的 host/port 启动 uvicorn
    uvicorn.run(app, host=config.HOST, port=config.PORT, reload=True)