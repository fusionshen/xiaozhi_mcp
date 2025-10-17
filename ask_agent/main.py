"""
main.py
---------------------------------
主服务入口，整合 LLM 解析、公式匹配、平台查询。
支持 GET/POST 调用。
确保 formula_api 初始化只执行一次。
"""

import os
for key in ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"]:
    os.environ.pop(key, None)

import asyncio
from fastapi import FastAPI, Query, Request
from agent_state import get_state, update_state, cleanup_expired_sessions
from llm_parser import parse_user_input
from tools import formula_api, platform_api

TOP_N = 5  # 显示候选数量

app = FastAPI(title="轻量智能体服务")

# ===========================================================
# 启动事件：初始化公式数据 + 定期清理
# ===========================================================
@app.on_event("startup")
async def startup_event():
    """
    在服务启动时执行：
      - 初始化公式数据（同步加载）；
      - 启动清理任务；
    """
    try:
        # 只初始化一次，不会重复加载
        formula_api.initialize()
    except Exception as e:
        import logging
        logging.exception("Failed to initialize formula_api: %s", e)

    # 定期清理过期 session
    asyncio.create_task(cleanup_expired_sessions())


# ===========================================================
# Chat API 接口
# ===========================================================
@app.get("/chat")
async def chat_get(
    user_id: str = Query(..., description="用户唯一标识，例如 test1"),
    message: str = Query(..., description="用户输入内容，例如 '查询2030酸轧纯水使用量'")
):
    """GET 版本 - 用于调试"""
    return await handle_chat(user_id, message)


@app.post("/chat")
async def chat_post(request: Request):
    """POST 版本 - 用于前端调用"""
    data = await request.json()
    user_id = data.get("user_id")
    message = data.get("message", "").strip()
    return await handle_chat(user_id, message)


# ===========================================================
# Chat 核心处理逻辑
# ===========================================================
async def handle_chat(user_id: str, user_input: str):
    """
    处理与用户的对话逻辑，包括：
      1. 状态管理；
      2. 解析输入；
      3. 匹配公式；
      4. 调用平台查询；
    """
    if not user_input:
        return {"message": "请输入指标名称或时间。", "state": await get_state(user_id)}

    # 获取或初始化用户状态
    state = await get_state(user_id)  # 注意此处加 await
    state.setdefault("slots", {
        "indicator": None,      # 指标名称
        "formula": None,        # 确认公式ID
        "formula_candidates": None,
        "awaiting_confirmation": False,
        "timeString": None,
        "timeType": None
    })
    slots = state["slots"]

    # Step0: 等待用户确认 top1
    if slots.get("awaiting_confirmation"):
        if user_input.lower() in ["是", "y", "yes"]:
            chosen = slots["formula_candidates"][0]
            slots["formula"] = chosen["FORMULAID"]
            slots["indicator"] = chosen["FORMULANAME"]
            slots["formula_candidates"] = None
            slots["awaiting_confirmation"] = False
            await update_state(user_id, state)
        elif user_input.lower() in ["否", "n", "no"]:
            candidates = slots["formula_candidates"][:TOP_N]
            msg_lines = ["请从以下候选公式选择编号："]
            for c in candidates:
                msg_lines.append(f"{c['number']}) {c['FORMULANAME']} (score {c.get('score', 0)})")
            return {"message": "\n".join(msg_lines), "state": state}
        else:
            return {"message": "请输入“是”或“否”进行确认。", "state": state}

    # Step1: 检查候选编号选择
    elif slots.get("formula_candidates"):
        if user_input.isdigit():
            idx = int(user_input.strip()) - 1
            candidates = slots["formula_candidates"]
            if 0 <= idx < len(candidates):
                chosen = candidates[idx]
                slots["formula"] = chosen["FORMULAID"]
                slots["indicator"] = chosen["FORMULANAME"]
                slots["formula_candidates"] = None
                await update_state(user_id, state)
            else:
                return {"message": f"请输入编号 1-{len(candidates)} 选择公式。", "state": state}
        else:
            return {"message": f"请输入编号 1-{len(slots['formula_candidates'])} 选择公式。", "state": state}

    # Step2: 解析用户输入（使用 LLM）
    if not slots.get("indicator") or not slots.get("timeString") or not slots.get("timeType"):
        parsed = await parse_user_input(user_input)
        slots["indicator"] = parsed.get("indicator") or slots.get("indicator")
        slots["timeString"] = parsed.get("timeString") or slots.get("timeString")
        slots["timeType"] = parsed.get("timeType") or slots.get("timeType")
        await update_state(user_id, state)

    # Step3: 检查指标
    if not slots["indicator"]:
        return {"message": "请告诉我你要查询的指标名称。", "state": state}

    # Step4: 检查时间
    if not (slots["timeString"] and slots["timeType"]):
        return {"message": f"好的，要查【{slots['indicator']}】，请告诉我时间。", "state": state}

    # Step5: 查询公式（调用 formula_api）
    formula_resp = await asyncio.to_thread(formula_api.formula_query, slots["indicator"])

    if formula_resp.get("done"):
        slots["formula"] = formula_resp["exact_matches"][0]["FORMULAID"]
        slots["indicator"] = formula_resp["exact_matches"][0]["FORMULANAME"]
    else:
        candidates = formula_resp.get("candidates", [])
        if candidates:
            if candidates[0]["score"] > 95:
                slots["formula_candidates"] = candidates[:TOP_N]
                slots["awaiting_confirmation"] = True
                await update_state(user_id, state)
                return {"message": f"我找到最匹配的公式 `{candidates[0]['FORMULANAME']}`，是否使用？（是/否）", "state": state}
            else:
                slots["formula_candidates"] = candidates[:TOP_N]
                await update_state(user_id, state)
                msg_lines = ["请从以下候选公式选择编号："]
                for c in candidates[:TOP_N]:
                    msg_lines.append(f"{c['number']}) {c['FORMULANAME']} (score {c.get('score', 0)})")
                return {"message": "\n".join(msg_lines), "state": state}
        else:
            return {"message": "未找到匹配公式，请重新输入指标名称。", "state": state}

    await update_state(user_id, state)

    # Step6: 调用平台 API 查询结果
    result = await platform_api.query_platform(
        formula=slots["formula"],
        timeString=slots["timeString"],
        timeType=slots["timeType"]
    )

    # Step7: 返回结果
    reply_lines = [
        f"✅ 指标: {slots['indicator']}",
        f"公式编码: {slots['formula']}",
        f"时间: {slots['timeString']} ({slots['timeType']})",
        f"结果: {result.get('value')} {result.get('unit', '')}"
    ]
    return {"message": "\n".join(reply_lines), "state": state}
