# core/llm_client.py
import os
import logging
import re
import json
import httpx
from langchain.schema import HumanMessage
from config import REMOTE_OLLAMA_URL, REMOTE_MODEL, LOCAL_MODEL

# ===================== 强制禁用系统代理 =====================
for key in ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"]:
    os.environ.pop(key, None)

# ===================== Logger =====================
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

# ===================== 全局共享直连 AsyncClient =====================
_global_client: httpx.AsyncClient | None = None

def get_global_client(timeout: float = 10.0) -> httpx.AsyncClient:
    """
    返回全局共享 AsyncClient，保证完全直连远程 Ollama，不走系统代理。
    """
    global _global_client
    if _global_client is None:
        transport = httpx.AsyncHTTPTransport(retries=0)
        _global_client = httpx.AsyncClient(
            timeout=timeout,
            transport=transport,
            trust_env=False,  # ⭐ 不使用系统代理
        )
    return _global_client

# ===================== 自定义 ChatOllama =====================
class DirectChatOllama(ChatOllama):
    """
    强制直连远程 Ollama，完全忽略系统代理。
    """
    def __init__(self, *args, **kwargs):
        timeout = kwargs.pop("timeout", 10.0)
        kwargs["client"] = get_global_client(timeout)
        super().__init__(*args, **kwargs)

# ===================== 检查远程 Ollama =====================
async def is_remote_ollama_available(base_url: str, timeout: float = 3.0) -> bool:
    try:
        client = get_global_client(timeout)
        resp = await client.get(f"{base_url}/api/tags")
        return resp.status_code == 200
    except Exception as e:
        logger.info(f"⚠️ Remote Ollama not reachable: {e}")
        return False

# ===================== 获取 LLM =====================
async def get_llm() -> DirectChatOllama:
    """
    优先使用远程 Ollama 模型，如果远程不可用则回退到本地模型。
    """
    if await is_remote_ollama_available(REMOTE_OLLAMA_URL):
        logger.info(f"🌐 Using remote Ollama model: {REMOTE_MODEL}")
        return DirectChatOllama(model=REMOTE_MODEL, base_url=REMOTE_OLLAMA_URL)
    else:
        logger.info(f"🔄 Falling back to local model: {LOCAL_MODEL}")
        return DirectChatOllama(model=LOCAL_MODEL)

# ===================== 安全解析 JSON =====================
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
            try:
                return json.loads(text[start:end+1])
            except json.JSONDecodeError:
                pass

        matches = re.findall(r"\{[\s\S]*?\}", text)
        for m in matches:
            try:
                return json.loads(m)
            except json.JSONDecodeError:
                continue

        # 再兜底：key:value 简单解析（保守）
        pairs = re.findall(r'"(\w+)"\s*:\s*"([^"]*)"', text)
        if pairs:
            return {k: v for k, v in pairs}

        logger.warning("⚠️ 未识别到 JSON 格式，返回空 dict。原文: %s", text[:400])
        return {}
    except Exception as e:
        logger.exception("❌ safe_llm_parse 解析失败:", e)
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

# ===================== 清理全局 AsyncClient（程序退出时可调用） =====================
async def close_global_client():
    global _global_client
    if _global_client:
        await _global_client.aclose()
        _global_client = None
