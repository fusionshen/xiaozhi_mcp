import asyncio

async def query_platform(formula: str, date: str):
    # 模拟调用外部 API
    await asyncio.sleep(0.3)
    return {"value": 12345, "unit": "吨"}
