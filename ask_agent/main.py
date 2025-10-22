# main.py
import os
for key in ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"]:
    os.environ.pop(key, None)

import asyncio
import time
import logging
from fastapi import FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from agent_state import get_state, update_state, cleanup_expired_sessions
from llm_parser import parse_user_input
from tools import formula_api, platform_api

TOP_N = 5  # 显示候选数量

# ----------------------
# 初始化日志
# ----------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
logger = logging.getLogger(__name__)

# ----------------------
# FastAPI 应用
# ----------------------
app = FastAPI(title="轻量智能体服务")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"]
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


# ----------------------
# GET/POST 接口
# ----------------------
@app.get("/chat")
async def chat_get(
    user_id: str = Query(..., description="用户唯一标识，例如 test1"),
    message: str = Query(..., description="用户输入内容，例如 '查询2030酸轧纯水使用量'")
):
    return await handle_chat(user_id, message)


@app.post("/chat")
async def chat_post(request: Request):
    data = await request.json()
    return await handle_chat(data.get("user_id"), data.get("message", "").strip())


# ----------------------
# 核心处理逻辑
# ----------------------
async def handle_chat(user_id: str, user_input: str):
    """
    处理与用户的对话逻辑，包括：
      1. 状态管理；
      2. 解析输入；
      3. 匹配公式；
      4. 调用平台查询；
    """
    total_start = time.time()
    logger.info(f"🟢 [handle_chat] 开始处理 user={user_id}, input={user_input!r}")

    try:
        if not user_input:
            return {"message": "请输入指标名称或时间。", "state": await get_state(user_id)}

        # Step0: 获取状态
        state = await get_state(user_id)
        state.setdefault("slots", {
            "indicator": None,
            "formula": None,
            "formula_candidates": None,
            "awaiting_confirmation": False,
            "timeString": None,
            "timeType": None
        })
        slots = state["slots"]
        logger.info(f"✅ 当前 slots: {slots}")

        # Step1️⃣ 若当前存在候选公式且输入为数字 => 直接选择并执行查询（跳过 LLM）
        if slots.get("formula_candidates") and user_input.isdigit():
            idx = int(user_input.strip()) - 1
            candidates = slots["formula_candidates"]

            if 0 <= idx < len(candidates):
                chosen = candidates[idx]
                slots["formula"] = chosen["FORMULAID"]
                slots["indicator"] = chosen["FORMULANAME"]
                slots["formula_candidates"] = None
                slots["awaiting_confirmation"] = False
                await update_state(user_id, state)
                logger.info(f"✅ 用户选择公式编号 {idx+1}: {chosen['FORMULANAME']}")

                # 若没有时间信息，则提示补全时间
                if not (slots.get("timeString") and slots.get("timeType")):
                    return {"message": f"好的，要查【{slots['indicator']}】，请告诉我时间。", "state": state}

                # ✅ 直接调用平台查询，不再经过 llm_parser
                t1 = time.time()
                result = await platform_api.query_platform(
                    formula=slots["formula"],
                    timeString=slots["timeString"],
                    timeType=slots["timeType"]
                )
                logger.info(f"✅ platform_api.query_platform 用时 {time.time() - t1:.2f}s, result={result}")

                reply_lines = [
                    f"✅ 指标: {slots['indicator']}",
                    f"公式编码: {slots['formula']}",
                    f"时间: {slots['timeString']} ({slots['timeType']})",
                    f"结果: {result.get(slots['formula'])} {result.get('unit', '')}"
                ]

                # 清空状态
                state["slots"] = {
                    "indicator": None,
                    "formula": None,
                    "formula_candidates": None,
                    "awaiting_confirmation": False,
                    "timeString": None,
                    "timeType": None
                }
                await update_state(user_id, state)
                logger.info(f"✅ handle_chat 全流程完成，用时 {time.time() - total_start:.2f}s")
                return JSONResponse(content={"message": "\n".join(reply_lines), "state": state})

            else:
                return {"message": f"请输入编号 1-{len(candidates)} 选择公式。", "state": state}

        # Step2️⃣ 若存在候选但输入不是数字 => 清空候选重新解析
        if slots.get("formula_candidates"):
            logger.info("🧩 非数字输入，清空候选列表并重新解析输入。")
            slots["formula_candidates"] = None
            slots["formula"] = None
            await update_state(user_id, state)

        # Step3️⃣ 正常调用 llm_parser 解析
        parsed = await parse_user_input(user_input)
        logger.info(f"🔍 LLM 解析结果: {parsed}")

        # 合并 slots（仅补全缺失信息，不覆盖已有）
        for key in ["indicator", "timeString", "timeType"]:
            if parsed.get(key):
                slots[key] = parsed[key]
        await update_state(user_id, state)

        # Step4️⃣ 若 indicator 缺失
        if not slots.get("indicator"):
            return {"message": "请告诉我您要查询的指标名称。", "state": state}

        # Step5️⃣ 调用 formula_api 匹配公式
        if not slots.get("formula") and slots.get("indicator"):
            t0 = time.time()
            formula_resp = await asyncio.to_thread(formula_api.formula_query_dict, slots["indicator"])
            logger.info(f"✅ formula_api.formula_query_dict 用时 {time.time() - t0:.2f}s")

            if formula_resp.get("done"):
                slots["formula"] = formula_resp["exact_matches"][0]["FORMULAID"]
                slots["indicator"] = formula_resp["exact_matches"][0]["FORMULANAME"]
                await update_state(user_id, state)
                logger.info(f"✅ 精确匹配公式: {slots['indicator']}")
            else:
                candidates = formula_resp.get("candidates", [])
                if candidates:
                    slots["formula_candidates"] = candidates[:TOP_N]
                    await update_state(user_id, state)
                    msg_lines = ["请从以下候选公式选择编号："]
                    for c in candidates[:TOP_N]:
                        msg_lines.append(f"{c['number']}) {c['FORMULANAME']} (score {c.get('score', 0):.2f})")
                    return {"message": "\n".join(msg_lines), "state": state}
                else:
                    return {"message": "未找到匹配公式，请重新输入指标名称。", "state": state}

        # Step6️⃣ 检查时间信息
        if not (slots.get("timeString") and slots.get("timeType")):
            return {"message": f"好的，要查【{slots['indicator']}】，请告诉我时间。", "state": state}

        # Step7️⃣ 调用平台接口
        t1 = time.time()
        result = await platform_api.query_platform(
            formula=slots["formula"],
            timeString=slots["timeString"],
            timeType=slots["timeType"]
        )
        logger.info(f"✅ platform_api.query_platform 用时 {time.time() - t1:.2f}s, result={result}")

        reply_lines = [
            f"✅ 指标: {slots['indicator']}",
            f"公式编码: {slots['formula']}",
            f"时间: {slots['timeString']} ({slots['timeType']})",
            f"结果: {result.get(slots['formula'])} {result.get('unit', '')}"
        ]

        # Step8️⃣ 清空 slots
        state["slots"] = {
            "indicator": None,
            "formula": None,
            "formula_candidates": None,
            "awaiting_confirmation": False,
            "timeString": None,
            "timeType": None
        }
        await update_state(user_id, state)
        logger.info(f"✅ handle_chat 全流程完成，用时 {time.time() - total_start:.2f}s")

        return JSONResponse(content={"message": "\n".join(reply_lines), "state": state})

    except Exception as e:
        logger.exception("❌ handle_chat 异常: %s", e)
        return JSONResponse(content={"error": str(e), "state": await get_state(user_id)}, status_code=500)
