# app/core/llm/llm_client.py
import os
import logging
import re
import json
import asyncio
import httpx
from typing import Optional, Dict, Any
from langchain.schema import HumanMessage

from config import (
    LLM_CHAIN,
    LLM_API_URL,
    LLM_API_KEY,
    LLM_API_TIMEOUT,
    REMOTE_OLLAMA_URL,
    REMOTE_MODEL,
    LOCAL_MODEL,
)

# ===================== 强制禁用系统代理 =====================
for key in ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"]:
    os.environ.pop(key, None)

# ===================== Logger =====================
logger = logging.getLogger("core.llm_client")
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

# ===================== 全局直连 AsyncClient =====================
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


# ============================================================
#                STEP 1 — API 调用（Dify / 自定义 API）
# ============================================================
async def _try_api_call(prompt: str) -> Optional[str]:
    if not LLM_API_URL or not LLM_API_KEY:
        return None

    headers = {
        "Authorization": f"Bearer {LLM_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "inputs": {},
        "query": prompt,
        "response_mode": "blocking",
        "conversation_id": "",
        "user": "py_client"
    }

    timeout = httpx.Timeout(LLM_API_TIMEOUT)

    async with httpx.AsyncClient(timeout=timeout) as client:
        for attempt in range(2):
            try:
                resp = await client.post(LLM_API_URL, headers=headers, json=payload)
                data = resp.json()

                if resp.status_code == 200 and "answer" in data:
                    return data["answer"].strip()

                logger.warning(f"API 返回无效内容: {data}")

            except Exception as e:
                err = type(e).__name__
                msg = str(e).split("\n")[0][:200]
                logger.error(f"API 调用失败: {err} - {msg}")

            await asyncio.sleep(1)

    return None


def _extract_json(text: str) -> Optional[Dict[Any, Any]]:
    if not text:
        return None

    # 1️⃣ 删除 <think> 推理内容
    text = re.sub(r'<think>.*?</think>\s*', '', text, flags=re.DOTALL).strip()

    # 2️⃣ 清理常见包裹字符
    text = text.replace("```json", "").replace("```", "").strip()
    text = text.replace("JSON:", "").replace("json:", "").strip()

    # 3️⃣ 提取最外层 JSON 找第一个 '{' 和最后一个 '}' —— 保证取到最外层 JSON（比非贪婪正则更稳）
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        json_str = text[start:end + 1]
        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            pass  # 继续走下一步兜底

    # 4️⃣ 非贪婪匹配多个 JSON，取第一个可解析的（旧逻辑）
    matches = re.findall(r"\{[\s\S]*?\}", text)
    for m in matches:
        try:
            return json.loads(m)
        except json.JSONDecodeError:
            continue

    # 5️⃣ 再兜底：匹配 "key": "value" 的格式（旧逻辑）
    pairs = re.findall(r'"(\w+)"\s*:\s*"([^"]*)"', text)
    if pairs:
        return {k: v for k, v in pairs}

    return None



# ============================================================
#    STEP 2 — 构造统一 LLM：优先 API → remote → local
# ============================================================
async def _get_unified_answer(prompt: str) -> str:
    """
    通用统一 LLM 调度：
    根据 LLM_CHAIN = ["api", "remote", "local"]
    按顺序逐级尝试，成功则返回。
    """

    for provider in LLM_CHAIN:
        provider = provider.strip()

        # ===========================
        # 1) API 调用
        # ===========================
        if provider == "api":
            if LLM_API_URL and LLM_API_KEY:
                logger.info("🔌 尝试 API 调用 …")
                ans = await _try_api_call(prompt)
                if ans:
                    logger.info("🌐 API 成功")
                    return ans
                logger.warning("⚠️ API 失败，尝试下一个 provider")
            else:
                logger.warning("⚠️ 已配置 api 但缺少 LLM_API_URL 或 LLM_API_KEY")

        # ===========================
        # 2) remote_ollama
        # ===========================
        elif provider == "remote":
            logger.info("🔌 检查 remote ollama …")
            if await is_remote_ollama_available(REMOTE_OLLAMA_URL):
                try:
                    logger.info(f"🌐 尝试 remote ollama: {REMOTE_MODEL}")
                    llm = DirectChatOllama(model=REMOTE_MODEL, base_url=REMOTE_OLLAMA_URL)
                    resp = await llm.agenerate([[HumanMessage(content=prompt)]])
                    return resp.generations[0][0].message.content.strip()
                except Exception as e:
                    logger.warning(f"⚠️ remote ollama 调用失败: {e}")
            else:
                logger.warning("⚠️ remote ollama 不可用，尝试下一个 provider")

        # ===========================
        # 3) local_ollama
        # ===========================
        elif provider == "local":
            try:
                logger.info(f"💻 尝试 local ollama: {LOCAL_MODEL}")
                llm = DirectChatOllama(model=LOCAL_MODEL)
                resp = await llm.agenerate([[HumanMessage(content=prompt)]])
                return resp.generations[0][0].message.content.strip()
            except Exception as e:
                logger.warning(f"⚠️ local ollama 调用失败: {e}")

        else:
            logger.error(f"❌ 未识别的 LLM provider: {provider}")

    # =================================================
    # 所有 provider 失败，返回空字符串
    # =================================================
    logger.error("❌ 所有 provider 失败，返回空字符串")
    return ""



# ============================================================
#                     对外统一接口
# ============================================================
async def safe_llm_parse(prompt: str) -> dict:
    """
    统一解析为 JSON，内部自动选择 API / Remote / Local
    """
    answer = await _get_unified_answer(prompt)
    parsed = _extract_json(answer)
    return parsed or {}


async def safe_llm_chat(prompt: str) -> str:
    """
    统一聊天接口
    """
    return await _get_unified_answer(prompt)


# ===================== 清理全局 AsyncClient =====================
async def close_global_client():
    global _global_client
    if _global_client:
        await _global_client.aclose()
        _global_client = None
