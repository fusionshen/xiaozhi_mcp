# core/llm_client.py
import os
import logging
import re
for key in ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"]:
    os.environ.pop(key, None)
import json
import httpx
from langchain.schema import HumanMessage
from config import (
    REMOTE_OLLAMA_URL, REMOTE_MODEL, LOCAL_MODEL
)

# 日志配置（被导入时确保仅配置一次）
logger = logging.getLogger("llm_client")
if not logger.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )

# ===================== ChatOllama 兼容导入 =====================
try:
    from langchain_ollama import ChatOllama
    logger.info("✅ Using ChatOllama from langchain-ollama")
except ImportError:
    try:
        from langchain_community.chat_models import ChatOllama
        logger.info("✅ Using ChatOllama from langchain_community")
    except ImportError:
        from langchain.chat_models import ChatOllama
        logger.info("⚠️ Using ChatOllama from old langchain (may be deprecated)")


async def is_remote_ollama_available(base_url: str, timeout: float = 3.0) -> bool:
    """
    检查远程 Ollama 服务是否可访问。
    """
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(f"{base_url}/api/tags")
            if resp.status_code == 200:
                #print(f"🌐 Remote Ollama available at {base_url}")
                return True
    except Exception as e:
        logger.info(f"⚠️ Remote Ollama not reachable: {e}")
    return False


async def get_llm() -> ChatOllama:
    """
    优先使用远程 gemma3:27b，如果远程不可用则回退到本地 qwen2.5:1.5b。
    """
    if await is_remote_ollama_available(REMOTE_OLLAMA_URL):
        #print(f"✅ Using remote model: {REMOTE_MODEL}")
        return ChatOllama(model=REMOTE_MODEL, base_url=REMOTE_OLLAMA_URL)
    else:
        logger.info(f"🔄 Falling back to local model: {LOCAL_MODEL}")
        return ChatOllama(model=LOCAL_MODEL)


# ===================== 通用 LLM 调用函数 =====================
async def safe_llm_parse(prompt: str) -> dict:
    """
    安全解析 LLM 返回内容为 JSON。
    支持以下场景：
    - 模型返回纯 JSON
    - 模型返回前后带解释文字
    - 模型输出 markdown 代码块（如 ```json ... ```）
    """
    llm = await get_llm()
    try:
        resp = await llm.agenerate([[HumanMessage(content=prompt)]])
        response_text = resp.generations[0][0].message.content.strip()
        print(response_text)

        # 🧹 清理常见包裹字符
        text = response_text.strip()
        text = text.replace("```json", "").replace("```", "").strip()
        text = text.replace("JSON:", "").replace("json:", "").strip()

        # 找第一个 '{' 和最后一个 '}' —— 保证取到最外层 JSON（比非贪婪正则更稳）
        start = text.find('{')
        end = text.rfind('}')
        if start != -1 and end != -1 and end > start:
            json_str = text[start:end+1]
            try:
                data = json.loads(json_str)
                logger.info("✅ 从 LLM 输出中成功解析 JSON。")
                return data
            except json.JSONDecodeError as e_inner:
                logger.warning("⚠️ 从首尾大括号提取的 JSON 解析失败: %s. 尝试正则兜底。", e_inner)

        # 兜底：如果上面失败，尝试用正则找所有 {...} 并依次尝试解析（处理多 JSON 或嵌套复杂输出）
        matches = re.findall(r"\{[\s\S]*?\}", text)
        for m in matches:
            try:
                data = json.loads(m)
                logger.info("✅ 正则兜底解析到 JSON。")
                return data
            except json.JSONDecodeError:
                continue

        # 再兜底：key:value 简单解析（保守）
        pairs = re.findall(r'"(\w+)"\s*:\s*"([^"]*)"', text)
        if pairs:
            data = {k: v for k, v in pairs}
            logger.warning("⚠️ 使用正则键值对兜底解析 JSON。")
            return data

        logger.warning("⚠️ 未识别到 JSON 格式，返回空 dict。原文: %s", text[:400])
        return {}
    except Exception as e:
        logger.exception("❌ safe_llm_parse 解析失败: %s", e)
        return {}


# ===================== 通用聊天函数 =====================
async def safe_llm_chat(prompt: str) -> str:
    """
    让模型自由回答，返回纯文本。
    """
    llm = await get_llm()
    try:
        resp = await llm.agenerate([[HumanMessage(content=prompt)]])
        return resp.generations[0][0].message.content.strip()
    except Exception as e:
        logger.exception("❌ LLM 聊天失败:", e)
        return "抱歉，我暂时无法回答这个问题。"