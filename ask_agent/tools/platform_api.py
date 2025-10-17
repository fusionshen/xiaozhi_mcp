import aiohttp

async def query_platform(formula: str, timeString: str, timeType: str):
    """
    查询指定公式在特定时间的结果
    :param formula: 公式ID
    :param timeString: 时间字符串，例如 '2025-10-15 05:00'
    :param timeType: 时间类型，例如 'SHIFT'
    :return: dict {value: float, unit: str}
    """
    payload = {
        "formula": formula,
        "timeString": timeString,
        "timeType": timeType
    }

    url = "http://example.com/api/query"  # 替换成实际第三方接口
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload) as resp:
            resp.raise_for_status()
            data = await resp.json()
            return {
                "value": data.get("value", 0),
                "unit": data.get("unit", "")
            }
