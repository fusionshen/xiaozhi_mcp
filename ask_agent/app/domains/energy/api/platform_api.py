# app/domains/energy/api/platform_api.py
import aiohttp
import asyncio
import time
import hashlib
import logging
from config import (
    TENANT_NAME, APP_KEY, APP_SECRET, USER_NAME,
    LOGIN_URL, QUERY_URL, RANGE_QUERY_URL, TOKEN_EXPIRE_DURATION
)

# ================= 日志配置 =================
logger = logging.getLogger("domains.energy.api.platform_api")
if not logger.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )

_cached_token = None
_token_timestamp = 0


def md5_upper(source: str) -> str:
    """MD5 加密并转大写"""
    return hashlib.md5(source.encode("utf-8")).hexdigest().upper()


async def _get_token():
    """
    获取或刷新 token（缓存 TOKEN_EXPIRE_DURATION 时间）
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
            logger.info("🟢 登录返回：%s", data)

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


def is_range_query(time_string: str) -> bool:
    """判断是否为区间时间格式（包含 ～ 或 ~）"""
    if not time_string:
        return False
    return any(sym in time_string for sym in ["～", "~"])


async def query_platform(formula: str, timeString: str, timeType: str):
    """
    智能判断查询类型：
    - 若 timeString 含 “～” 或 “~” => 调区间接口 RANGE_QUERY_URL
    - 否则 => 调单点接口 QUERY_URL
    - timeType 始终原样透传
    """

    token = await _get_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    if is_range_query(timeString):
        # 区间查询: 例如 "2024-09-01~2024-09-07"
        start_date, end_date = [x.strip() for x in timeString.replace("～", "~").split("~", 1)]

        payload = {
            "startClock": start_date,
            "endClock": end_date,
            "formulas": {formula: formula},
            "timeGranId": timeType  # ✅ 传入原始 timeType，不强制改成 DAY
        }
        url = RANGE_QUERY_URL
    else:
        # 单点查询
        payload = {
            "expressionList": {formula: formula},
            "clock": timeString,
            "timegranId": timeType
        }
        url = QUERY_URL

    logger.info("🟡 调用接口: %s", url)
    logger.info("🧩 请求参数: %s", payload)

    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload, headers=headers) as resp:
            resp.raise_for_status()
            data = await resp.json()
            print("🟢 返回数据:", data)

            if "data" not in data:
                raise ValueError(f"接口返回格式错误: {data}")

            return data["data"]


# === 测试入口 ===
if __name__ == "__main__":
    async def main():
        # 单点查询示例
        result1 = await query_platform("GXNHLT1100.IXRL", "2022-10-02", "DAY")
        logger.info("📍 单点查询结果：%s", result1)

        # 区间查询示例
        result2 = await query_platform("GXNHLT1100.IXRL", "2022-09-01~2022-09-07", "DAY")
        logger.info("📅 区间查询结果：%s", result2)
        # 区间查询示例2
        result3 = await query_platform("GXNHLT1100.IXRL", "2022-09~2022-10", "MONTH")
        logger.info("📅 区间查询结果：%s", result3)

    asyncio.run(main())
