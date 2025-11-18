# core/llm_intent_parser.py
import logging
import asyncio
from core.llm_client import safe_llm_parse
from core.context_graph import ContextGraph, default_indicators
from core.pipeline_context import get_graph, set_graph

logger = logging.getLogger("llm_intent_parser")
if not logger.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )


async def parse_intent(user_id: str, user_input: str) -> dict:
    """
    新版轻量意图分类（基于 ContextGraph 状态）
    - graph_state: {
          "graph": {...},
          "meta": {
              "history": [...],
              "current_intent_info": {...}
          }
      }

    返回:
    {
        "intent": "ENERGY_QUERY" | "CHAT" | "TOOL" | "ENERGY_KNOWLEDGE_QA",
        "parsed_number": int 或 None
    }
    """
    # 获取 graph
    graph = get_graph(user_id)
    if not graph:
        graph = ContextGraph()
        set_graph(user_id, graph)
        logger.info("✨ 创建新的 ContextGraph")

    history = graph.get_history()

    # 提取上次指标和候选公式
    current_intent_info = graph.get_intent_info()
    indicators = current_intent_info.get("indicators", [])

    # ---------- 查找当前 active indicator ----------
    current_indicator = None
    for ind in indicators:
        if ind.get("status") == "active":
            current_indicator = ind
            break

    # 如果没有 active 的，就新建一个
    if not current_indicator:
        current_indicator = default_indicators()
        indicators.append(current_indicator)

    last_indicator = current_indicator.get("indicator")
    formula_candidates = current_indicator.get("formula_candidates", [])
    awaiting_confirmation = bool(formula_candidates)

    # 历史摘要
    history_summary = ""
    if history:
        recent = history[-3:]
        history_summary = "\n".join([
            f"- {h.get('ask')} -> {h.get('reply')[:200]}..." for h in recent
        ])

    # 槽位状态摘要
    slot_status = current_indicator.get("slot_status", {})
    slots_summary = "\n".join([
        f"{k}: {v}" for k, v in slot_status.items()
    ]) if slot_status else "(空)"

    # 候选公式概览
    candidates_summary = ""
    if formula_candidates:
        candidates_summary = "\n".join([
            f"{c['number']}) {c['FORMULANAME']} (score {c['score']:.2f})"
            for c in formula_candidates[:5]
        ])

    # 拼接 prompt
    prompt = f"""
你是一个智能意图识别器，根据上下文判断用户意图。
意图类型：
- ENERGY_QUERY: 用户想查询能源指标数据（包括初次查询、补充时间、或正在选择候选公式）
- ENERGY_KNOWLEDGE_QA: 解释能源概念或定义的问题
- CHAT: 普通闲聊或非结构化提问
- TOOL: 工具类问题（时间、日期、天气等）
用户输入: "{user_input}"
当前指标: "{last_indicator}"
最近对话: {history_summary if history_summary else '(无)'}
槽位状态: {slots_summary}
候选公式: {candidates_summary if candidates_summary else '(无)'}

规则优先级：
1. 如果用户正在选择候选公式：
   - 输入为数字或序号指代（如“1”“第二个”） → ENERGY_QUERY。
   - 输入与能源无关 → CHAT。
2. 如果当前处于能源查询流程，
   且用户输入包含时间表达（如“今天”“昨天”“2022年的今天”“上月”），
   则视为 ENERGY_QUERY —— 表示用户在补充查询时间，而不是单纯问时间。
3. 能源概念/定义/结构/用途类问题 → ENERGY_KNOWLEDGE_QA
4. 能源指标/单位/消耗量 → ENERGY_QUERY
5. 日期/时间/天气 → TOOL
6. 其他 → CHAT

⚠️ 强调：
- 问“是什么”“包括哪些”“用途”“定义”“作用”“组成”等能源相关概念性问题，必须返回 ENERGY_KNOWLEDGE_QA
- 问具体数值、消耗量、用量时才返回 ENERGY_QUERY

返回 JSON：
{{
  "intent": "ENERGY_QUERY" 或 "CHAT" 或 "TOOL" 或 "ENERGY_KNOWLEDGE_QA",
  "parsed_number": 若输入为候选编号或“选第一条”等 → 提取数字，否则为 null
}}
"""

    logger.info(f"🔍 [parse_intent] user_input='{user_input}', indicator='{last_indicator}', awaiting={awaiting_confirmation}")

    try:
        print(prompt)
        result = await safe_llm_parse(prompt)
        # 合并 LLM 返回（防止 LLM 也返回）
        intent = result.get("intent", "CHAT")
        parsed_number = result.get("parsed_number")
        logger.info(f"📥 轻量意图分类结果: intent={intent}, parsed_number={parsed_number}")
        return {"intent": intent, "parsed_number": parsed_number}
    except Exception as e:
        logger.exception("❌ LLM parse_intent 调用失败: %s", e)
        return {"intent": "CHAT", "parsed_number": None}


# ✅ main 测试函数
if __name__ == "__main__":
    import asyncio

    test_graph_state = {
        "graph": {
            "nodes": [
            {
                "id": 1,
                "indicator_entry": {
                "status": "completed",
                "indicator": "1高炉工序能耗实绩报出值",
                "formula": "GXNHLT1101.IXRL",
                "timeString": "2022-01-01",
                "timeType": "DAY",
                "slot_status": {
                    "formula": "filled",
                    "time": "filled"
                },
                "value": "381.65",
                "note": "✅ 1高炉工序能耗实绩报出值 在 2022-01-01 (DAY) 的值是 381.65 ",
                "formula_candidates": [
                    {
                    "number": 1,
                    "FORMULAID": "GXNHLT1101.IXPL",
                    "FORMULANAME": "1高炉工序能耗计划报出值",
                    "score": 91.7787,
                    "fuzzy_score": 95.4909,
                    "semantic_score": 81.9644,
                    "match_kind": "hybrid"
                    },
                    {
                    "number": 2,
                    "FORMULAID": "GXNHLT1101.IXPL.SUMVALUE",
                    "FORMULANAME": "1高炉工序能耗计划累计值",
                    "score": 88.6605,
                    "fuzzy_score": 92.6545,
                    "semantic_score": 83.2141,
                    "match_kind": "hybrid"
                    },
                    {
                    "number": 3,
                    "FORMULAID": "PHNHLT1101.IXPL",
                    "FORMULANAME": "1高炉工序平衡能耗计划报出值",
                    "score": 88.4603,
                    "fuzzy_score": 95.4909,
                    "semantic_score": 76.6991,
                    "match_kind": "hybrid"
                    },
                    {
                    "number": 4,
                    "FORMULAID": "GXNHLT1101.IXRL",
                    "FORMULANAME": "1高炉工序能耗实绩报出值",
                    "score": 87.768,
                    "fuzzy_score": 99.1636,
                    "semantic_score": 67.9943,
                    "match_kind": "hybrid"
                    },
                    {
                    "number": 5,
                    "FORMULAID": "GXNHLT1100.IXRL",
                    "FORMULANAME": "高炉工序能耗实绩报出值",
                    "score": 87.2049,
                    "fuzzy_score": 87.264,
                    "semantic_score": 75.0671,
                    "match_kind": "hybrid"
                    }
                ]
                },
                "intent_info_snapshot": {
                "user_input_list": [
                    "2022年1号高炉工序能耗是多少，对比计划偏差多少",
                    "4"
                ],
                "intent_list": [
                    "compare",
                    "clarify"
                ],
                "indicators": [
                    {
                    "status": "completed",
                    "indicator": "1高炉工序能耗实绩报出值",
                    "formula": "GXNHLT1101.IXRL",
                    "timeString": "2022-01-01",
                    "timeType": "DAY",
                    "slot_status": {
                        "formula": "filled",
                        "time": "filled"
                    },
                    "value": "381.65",
                    "note": "✅ 1高炉工序能耗实绩报出值 在 2022-01-01 (DAY) 的值是 381.65 ",
                    "formula_candidates": [
                        {
                        "number": 1,
                        "FORMULAID": "GXNHLT1101.IXPL",
                        "FORMULANAME": "1高炉工序能耗计划报出值",
                        "score": 91.7787,
                        "fuzzy_score": 95.4909,
                        "semantic_score": 81.9644,
                        "match_kind": "hybrid"
                        },
                        {
                        "number": 2,
                        "FORMULAID": "GXNHLT1101.IXPL.SUMVALUE",
                        "FORMULANAME": "1高炉工序能耗计划累计值",
                        "score": 88.6605,
                        "fuzzy_score": 92.6545,
                        "semantic_score": 83.2141,
                        "match_kind": "hybrid"
                        },
                        {
                        "number": 3,
                        "FORMULAID": "PHNHLT1101.IXPL",
                        "FORMULANAME": "1高炉工序平衡能耗计划报出值",
                        "score": 88.4603,
                        "fuzzy_score": 95.4909,
                        "semantic_score": 76.6991,
                        "match_kind": "hybrid"
                        },
                        {
                        "number": 4,
                        "FORMULAID": "GXNHLT1101.IXRL",
                        "FORMULANAME": "1高炉工序能耗实绩报出值",
                        "score": 87.768,
                        "fuzzy_score": 99.1636,
                        "semantic_score": 67.9943,
                        "match_kind": "hybrid"
                        },
                        {
                        "number": 5,
                        "FORMULAID": "GXNHLT1100.IXRL",
                        "FORMULANAME": "高炉工序能耗实绩报出值",
                        "score": 87.2049,
                        "fuzzy_score": 87.264,
                        "semantic_score": 75.0671,
                        "match_kind": "hybrid"
                        }
                    ]
                    },
                    {
                    "status": "active",
                    "indicator": "1号高炉工序能耗计划",
                    "formula": None,
                    "timeString": "2022-01",
                    "timeType": "MONTH",
                    "slot_status": {
                        "formula": "missing",
                        "time": "filled"
                    },
                    "value": None,
                    "note": None,
                    "formula_candidates": None
                    }
                ]
                }
            }
            ],
            "relations": [],
            "_next_id": 2
        },
        "meta": {
            "history": [
            {
                "ask": "2022年1号高炉工序能耗是多少，对比计划偏差多少",
                "reply": "没有完全匹配的[1号高炉工序能耗]指标，请从以下候选选择编号(或者重新输入尽量精确的指标名称：\n1) 1高炉工序能耗计划报出值 (score 91.78)\n2) 1高炉工序能耗计划累计值 (score 88.66)\n3) 1高炉工序平衡能耗计划报出值 (score 88.46)\n4) 1高炉工序能耗实绩报出值 (score 87.77)\n5) 高炉工序能耗实绩报出值 (score 87.20)"
            },
            {
                "ask": "4 -> system:完成 clarify 并检测到 compare 上下文，继续执行 handle_compare...",
                "reply": "没有完全匹配的[1号高炉工序能耗计划]指标，请从以下候选选择编号(或者重新输入尽量精确的指标名称：\n1) 1高炉工序能耗计划报出值 (score 93.78)\n2) 高炉工序能耗计划报出值 (score 90.66)\n3) 1高炉工序平衡能耗计划报出值 (score 90.47)\n4) 1高炉工序能耗计划累计值 (score 90.09)\n5) 2高炉工序能耗计划报出值 (score 87.18)"
            }
            ],
            "current_intent_info": {
            "user_input_list": [
                "2022年1号高炉工序能耗是多少，对比计划偏差多少",
                "4",
                "4 -> system:完成 clarify 并检测到 compare 上下文，继续执行 handle_compare..."
            ],
            "intent_list": [
                "compare",
                "clarify",
                "compare"
            ],
            "indicators": [
                {
                "status": "completed",
                "indicator": "1高炉工序能耗实绩报出值",
                "formula": "GXNHLT1101.IXRL",
                "timeString": "2022-01-01",
                "timeType": "DAY",
                "slot_status": {
                    "formula": "filled",
                    "time": "filled"
                },
                "value": "381.65",
                "note": "✅ 1高炉工序能耗实绩报出值 在 2022-01-01 (DAY) 的值是 381.65 ",
                "formula_candidates": [
                    {
                    "number": 1,
                    "FORMULAID": "GXNHLT1101.IXPL",
                    "FORMULANAME": "1高炉工序能耗计划报出值",
                    "score": 91.7787,
                    "fuzzy_score": 95.4909,
                    "semantic_score": 81.9644,
                    "match_kind": "hybrid"
                    },
                    {
                    "number": 2,
                    "FORMULAID": "GXNHLT1101.IXPL.SUMVALUE",
                    "FORMULANAME": "1高炉工序能耗计划累计值",
                    "score": 88.6605,
                    "fuzzy_score": 92.6545,
                    "semantic_score": 83.2141,
                    "match_kind": "hybrid"
                    },
                    {
                    "number": 3,
                    "FORMULAID": "PHNHLT1101.IXPL",
                    "FORMULANAME": "1高炉工序平衡能耗计划报出值",
                    "score": 88.4603,
                    "fuzzy_score": 95.4909,
                    "semantic_score": 76.6991,
                    "match_kind": "hybrid"
                    },
                    {
                    "number": 4,
                    "FORMULAID": "GXNHLT1101.IXRL",
                    "FORMULANAME": "1高炉工序能耗实绩报出值",
                    "score": 87.768,
                    "fuzzy_score": 99.1636,
                    "semantic_score": 67.9943,
                    "match_kind": "hybrid"
                    },
                    {
                    "number": 5,
                    "FORMULAID": "GXNHLT1100.IXRL",
                    "FORMULANAME": "高炉工序能耗实绩报出值",
                    "score": 87.2049,
                    "fuzzy_score": 87.264,
                    "semantic_score": 75.0671,
                    "match_kind": "hybrid"
                    }
                ]
                },
                {
                "status": "active",
                "indicator": "1号高炉工序能耗计划",
                "formula": None,
                "timeString": "2022-01",
                "timeType": "MONTH",
                "slot_status": {
                    "formula": "missing",
                    "time": "filled"
                },
                "value": None,
                "note": None,
                "formula_candidates": [
                    {
                    "number": 1,
                    "FORMULAID": "GXNHLT1101.IXPL",
                    "FORMULANAME": "1高炉工序能耗计划报出值",
                    "score": 93.7797,
                    "fuzzy_score": 97.5371,
                    "semantic_score": 83.7753,
                    "match_kind": "hybrid"
                    },
                    {
                    "number": 2,
                    "FORMULAID": "GXNHLT1100.IXPL",
                    "FORMULANAME": "高炉工序能耗计划报出值",
                    "score": 90.6642,
                    "fuzzy_score": 88.88,
                    "semantic_score": 84.6033,
                    "match_kind": "hybrid"
                    },
                    {
                    "number": 3,
                    "FORMULAID": "PHNHLT1101.IXPL",
                    "FORMULANAME": "1高炉工序平衡能耗计划报出值",
                    "score": 90.4736,
                    "fuzzy_score": 97.5371,
                    "semantic_score": 78.5294,
                    "match_kind": "hybrid"
                    },
                    {
                    "number": 4,
                    "FORMULAID": "GXNHLT1101.IXPL.SUMVALUE",
                    "FORMULANAME": "1高炉工序能耗计划累计值",
                    "score": 90.0906,
                    "fuzzy_score": 94.64,
                    "semantic_score": 84.229,
                    "match_kind": "hybrid"
                    },
                    {
                    "number": 5,
                    "FORMULAID": "GXNHLT1102.IXPL",
                    "FORMULANAME": "2高炉工序能耗计划报出值",
                    "score": 87.1809,
                    "fuzzy_score": 88.88,
                    "semantic_score": 79.0764,
                    "match_kind": "hybrid"
                    }
                ]
                }
            ]
            }
        }
    }
    graph = ContextGraph.from_state(test_graph_state)
    set_graph("test_user", graph)
   
    async def test():
        result1 = await parse_intent("test_user", "选第一个")  # 今天 
        result2 = await parse_intent("test_user", "1")
        result3 = await parse_intent("test_user", "现在几点")
        result4 = await parse_intent("test_user", "1#，2#，3#高炉分别是多少")
        print("结果1:", result1)
        print("结果2:", result2)
        print("结果3:", result3)
        print("结果4:", result4)

    asyncio.run(test())
