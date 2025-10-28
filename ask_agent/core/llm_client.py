import os
for key in ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"]:
    os.environ.pop(key, None)
import json
import httpx
from langchain.schema import HumanMessage


# ===================== ChatOllama 兼容导入 =====================
try:
    from langchain_ollama import ChatOllama
    print("✅ Using ChatOllama from langchain-ollama")
except ImportError:
    try:
        from langchain_community.chat_models import ChatOllama
        print("✅ Using ChatOllama from langchain_community")
    except ImportError:
        from langchain.chat_models import ChatOllama
        print("⚠️ Using ChatOllama from old langchain (may be deprecated)")


# ===================== 模型优先级定义 =====================
REMOTE_OLLAMA_URL = "http://192.168.92.13:11434"  # ← 修改为你的远程 Ollama 地址
REMOTE_MODEL = "gemma3:27b"
LOCAL_MODEL = "qwen2.5:1.5b"


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
        print(f"⚠️ Remote Ollama not reachable: {e}")
    return False


async def get_llm() -> ChatOllama:
    """
    优先使用远程 gemma3:27b，如果远程不可用则回退到本地 qwen2.5:1.5b。
    """
    if await is_remote_ollama_available(REMOTE_OLLAMA_URL):
        #print(f"✅ Using remote model: {REMOTE_MODEL}")
        return ChatOllama(model=REMOTE_MODEL, base_url=REMOTE_OLLAMA_URL)
    else:
        print(f"🔄 Falling back to local model: {LOCAL_MODEL}")
        return ChatOllama(model=LOCAL_MODEL)


# ===================== 通用 LLM 调用函数 =====================
async def safe_llm_parse(prompt: str) -> dict:
    """
    调用 LLM 并安全解析 JSON 输出。
    - 自动去掉 ``` 或 ```json 包裹
    - JSON 解析失败时用正则兜底
    返回字典：{"indicator": ..., "timeString": ..., "timeType": ...} 或自定义字段
    """
    llm = await get_llm()
    try:
        resp = await llm.agenerate([[HumanMessage(content=prompt)]])
        content = resp.generations[0][0].message.content.strip()

        # 去掉 ``` 包裹
        if content.startswith("```"):
            content = "\n".join(content.splitlines()[1:-1]).strip()

        try:
            result = json.loads(content)
        except json.JSONDecodeError:
            # 正则兜底
            result = {}
            pairs = re.findall(r'"(\w+)"\s*:\s*"([^"]*)"', content)
            for k, v in pairs:
                result[k] = v

        return result

    except Exception as e:
        print("❌ LLM 调用失败:", e)
        return {}