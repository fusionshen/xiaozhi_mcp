import asyncio
from tools import formula_api, platform_api

async def query_multiple_indicators(graph):
    """
    并行查询多个指标的值：
    """
    results = {}

    async def query_one(indicator, time_str, time_type):
        # 1️⃣ 查找公式
        formula_resp = await asyncio.to_thread(formula_api.formula_query_dict, indicator)
        if not formula_resp.get("done") or not formula_resp.get("exact_matches"):
            return indicator, "未找到对应公式"

        formula_id = formula_resp["exact_matches"][0].get("FORMULAID")
        if not formula_id:
            return indicator, "公式信息不完整"

        # 2️⃣ 调用平台 API 查询
        try:
            result = await asyncio.to_thread(platform_api.query_platform,
                                             formula_id,
                                             time_str,
                                             time_type)
            return indicator, result
        except Exception as e:
            return indicator, f"查询失败：{e}"

    tasks = []
    for ind in graph.indicators:
        for t in graph.times:
            tasks.append(query_one(ind, t["timeString"], t.get("timeType")))

    for ind, result in await asyncio.gather(*tasks):
        results[ind] = result

    return results
