import os
for key in ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"]:
    os.environ.pop(key, None)
import asyncio
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from llm_parser import parse_user_input
from core.llm_intent_parser import parse_user_intent
from tools import formula_api, platform_api
from core.context_graph import ContextGraph
from core.pipeline import Pipeline
from core.query_engine import QueryEngine

# ===================== FastAPI 初始化 =====================
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ===================== 全局上下文图 =====================
context_graph = ContextGraph()
pipeline = Pipeline(context_graph)
query_engine = QueryEngine(context_graph)

# ===================== 核心接口 =====================
@app.get("/chat")
async def chat_get(
    user_id: str = Query(..., description="用户唯一标识"),
    message: str = Query(..., description="用户输入内容")
):
    # 1️⃣ 解析用户意图
    intent = await parse_user_intent(message)

    # 2️⃣ 解析用户指标和时间
    parsed = await parse_user_input(message)

    # 3️⃣ 构建上下文节点
    context_graph.update_user_context(user_id, {
        "last_input": message,
        "parsed": parsed,
        "intent": intent
    })

    # 4️⃣ 根据 intent 执行不同动作
    result = None
    if intent == "compare":
        # 对比查询：复用上次指标，换时间
        last_query = context_graph.get_last_query(user_id)
        if last_query:
            parsed["indicator"] = last_query.get("indicator")
            result = query_engine.query(parsed)
        else:
            result = query_engine.query(parsed)
    elif intent == "same_indicator_new_time":
        last_query = context_graph.get_last_query(user_id)
        if last_query:
            parsed["indicator"] = last_query.get("indicator")
        result = query_engine.query(parsed)
    elif intent == "expand":
        # 扩展查询：例如多个对象循环调用 formula_api
        indicators = parsed.get("indicator")
        if isinstance(indicators, list):
            result = [query_engine.query({"indicator": ind, "timeString": parsed.get("timeString")}) for ind in indicators]
        else:
            result = query_engine.query(parsed)
    elif intent == "list_query":
        # 汇总统计查询
        result = query_engine.aggregate(parsed)
    else:  # new_query
        result = query_engine.query(parsed)

    # 5️⃣ 返回结果
    return {
        "user_id": user_id,
        "input": message,
        "intent": intent,
        "parsed": parsed,
        "result": result
    }

