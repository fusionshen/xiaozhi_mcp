import aiohttp
import asyncio
import time
import hashlib
from config import (
    TENANT_NAME, APP_KEY, APP_SECRET, USER_NAME,
    LOGIN_URL, QUERY_URL, TOKEN_EXPIRE_DURATION
)

_cached_token = None
_token_timestamp = 0


def md5_upper(source: str) -> str:
    """MD5 加密并转大写"""
    return hashlib.md5(source.encode("utf-8")).hexdigest().upper()


async def _get_token():
    """
    获取或刷新 token（缓存 TOKEN_EXPIRE_DURATION）
    """
    global _cached_token, _token_timestamp
    now = time.time()

    # 若缓存未过期则直接返回
    if _cached_token and (now - _token_timestamp) < TOKEN_EXPIRE_DURATION.total_seconds():
        return _cached_token

    # 生成加密签名
    ts = int(now * 1000)
    enc_source = f"{TENANT_NAME}:{APP_KEY}:{USER_NAME}:{ts}:{APP_SECRET}"
    enc = md5_upper(enc_source)

    body = {
        "appId": APP_KEY,
        "userName": USER_NAME,
        "tenancyName": TENANT_NAME,
        "timestamp": ts,
        "enc": enc
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(LOGIN_URL, json=body) as resp:
            resp.raise_for_status()
            data = await resp.json()
            print("🟢 登录返回：", data)

            # token 位于 data.data.token
            token = (
                data.get("data", {}).get("token") or  # ✅ 正确路径
                data.get("token") or
                data.get("data")
            )

            if not token:
                raise ValueError(f"登录接口未返回有效 token: {data}")

            _cached_token = token
            _token_timestamp = now
            return token


async def query_platform(formula: str, timeString: str, timeType: str):
    """
    查询指定公式在特定时间的结果
    """
    token = await _get_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    print(headers)
    payload = {
        "expressionList": {formula: formula},
        "clock": timeString,
        "timegranId": timeType
    }
    print(payload)
    async with aiohttp.ClientSession() as session:
        async with session.post(QUERY_URL, json=payload, headers=headers) as resp:
            resp.raise_for_status()
            data = await resp.json()
            print(data)
            if "data" not in data:
                raise ValueError(f"接口返回格式错误: {data}")

            return data["data"]

# === 测试入口 ===
if __name__ == "__main__":
    async def main():
        result = await query_platform("GXNHLT1100.IXRL", "2022-10-02", "DAY")
        print("查询结果：", result)

    asyncio.run(main())
