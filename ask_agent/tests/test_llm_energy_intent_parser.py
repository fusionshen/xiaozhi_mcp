import asyncio
from core.llm_energy_intent_parser import EnergyIntentParser
import json

TSET_CASES = [
        "本月1，2，3高炉工序能耗分别是多少",
        "高炉工序能耗是多少，对比计划偏差多少",
        "本月高炉工序能耗是多少，对比计划偏差多少",
        "今天",
        "高炉今天的工序能耗是多少",
        "本月累计的高炉工序能耗是多少",
        "1号高炉昨天的工序能耗是多少",
        "去年今天的高炉工序能耗是多少",
        "2021年10月23日的1高炉工序能耗是多少",
        "时间：2021-10-23，1高炉工序能耗是多少",
        "高炉工序能耗是多少",
        "本月1、2号高炉工序能耗是多少",
        "高炉工序能耗本月计划是多少",
        "本月高炉工序能耗的计划值是多少",
        "今天的高炉工序能耗是多少",
        "对比上月有什么变化",
        "本月的1高炉工序能耗是多少？",
        "对比2高炉有什么变化",
        "本月的高炉电耗是多少",
        "本月的高炉电使用量是多少",
        "高炉的煤气耗是多少",
        "10号高炉今天的工序能耗是多少",
        "本月的高炉工序能耗是多少？",
        "1#，2#，3#高炉分别是多少",
        "本月高炉工序能耗是多少，对比计划偏差多少",
        "本年度的高炉工序能耗趋势是什么样的",
        "本月1、2号高炉工序能耗偏差情况"
    ]

async def main():
    parser = EnergyIntentParser()

    test_inputs = ['它们对比呢？']

    for t in test_inputs:
        result = await parser.parse_intent(t)
        print(f"\n🧠 输入: {t}\n➡️ 解析结果: {json.dumps(result, ensure_ascii=False, indent=2)}")


if __name__ == "__main__":
    asyncio.run(main())
