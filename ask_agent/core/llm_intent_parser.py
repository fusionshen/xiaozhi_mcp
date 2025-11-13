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

    # 构建最近历史摘要
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
你是一个智能意图识别器，请根据上下文判断当前用户输入属于哪类意图。

意图类型：
- ENERGY_QUERY: 用户想查询能源指标数据（包括初次查询、补充时间、或正在选择候选公式）
- CHAT: 普通闲聊或非结构化提问
- TOOL: 工具类问题（时间、日期、天气等）
- ENERGY_KNOWLEDGE_QA: 解释能源概念或定义的问题

当前上下文：
- 用户输入: "{user_input}"
- 当前指标: "{last_indicator}"
- 最近对话记录:
{history_summary if history_summary else '(无)'}
- 当前槽位状态:
{slots_summary}
- 当前候选公式:
{candidates_summary if candidates_summary else '(无)'}

识别规则（优先级从高到低）：
1. 如果用户正在选择候选公式：
   - 输入为数字或序号指代（如“1”“第二个”） → ENERGY_QUERY。
   - 输入与能源无关 → CHAT。
2. 如果当前处于能源查询流程，
   且用户输入包含时间表达（如“今天”“昨天”“2022年的今天”“上月”），
   则视为 ENERGY_QUERY —— 表示用户在补充查询时间，而不是单纯问时间。
3. 如果用户输入包含能源指标、单位、能耗类词汇（如“电耗”“高炉煤气使用量”），
   视为 ENERGY_QUERY。
4. 如果用户提问能源定义、概念、用途 → ENERGY_KNOWLEDGE_QA。
5. 如果输入与能源查询流程无关且是日期、时间、天气类问题 → TOOL。
6. 其他普通问答 → CHAT。

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
            "nodes": [],
            "relations": [],
            "_next_id": 1
        },
        "meta": {
            "history": [
                {
                    "ask": "1号高炉工序能耗",
                    "reply": "请从以下候选公式选择编号：\n1) 1高炉工序能耗实绩报出值 (score 87.77)\n2) 高炉工序能耗实绩报出值 (score 87.20)\n3) 1高炉工序平衡能耗实绩报出值 (score 86.29)\n4) 高炉工序能耗实绩累计值 (score 85.74)\n5) 1高炉工序平衡能耗实绩累计值 (score 85.73)"
                }
                ],
                "current_intent_info": {
                "user_input": "1号高炉工序能耗",
                "intent": "single_query",
                "indicators": [
                    {
                    "status": "active",
                    "indicator": "1号高炉工序能耗",
                    "formula": None,
                    "timeString": None,
                    "timeType": None,
                    "slot_status": {
                        "formula": "missing",
                        "time": "missing"
                    },
                    "value": None,
                    "note": None,
                    "formula_candidates": [
                        {
                            "number": 1,
                            "FORMULAID": "GXNHLT1101.IXRL",
                            "FORMULANAME": "1高炉工序能耗实绩报出值",
                            "score": 87.768,
                            "fuzzy_score": 99.1636,
                            "semantic_score": 67.9943,
                            "match_kind": "hybrid"
                        },
                        {
                            "number": 2,
                            "FORMULAID": "GXNHLT1100.IXRL",
                            "FORMULANAME": "高炉工序能耗实绩报出值",
                            "score": 87.2049,
                            "fuzzy_score": 87.264,
                            "semantic_score": 75.0671,
                            "match_kind": "hybrid"
                        },
                        {
                            "number": 3,
                            "FORMULAID": "PHNHLT1101.IXRL",
                            "FORMULANAME": "1高炉工序平衡能耗实绩报出值",
                            "score": 86.2949,
                            "fuzzy_score": 99.1636,
                            "semantic_score": 65.7436,
                            "match_kind": "hybrid"
                        },
                        {
                            "number": 4,
                            "FORMULAID": "GXNHLT1100.IXRL.SUMVALUE",
                            "FORMULANAME": "高炉工序能耗实绩累计值",
                            "score": 85.7415,
                            "fuzzy_score": 84.672,
                            "semantic_score": 78.5695,
                            "match_kind": "hybrid"
                        },
                        {
                            "number": 5,
                            "FORMULAID": "PHNHLT1101.IXRL.SUMVALUE",
                            "FORMULANAME": "1高炉工序平衡能耗实绩累计值",
                            "score": 85.7281,
                            "fuzzy_score": 96.2182,
                            "semantic_score": 70.851,
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
        result2 = await parse_intent("test_user", "今天的能耗")
        result3 = await parse_intent("test_user", "现在几点")
        print("结果1:", result1)
        print("结果2:", result2)
        print("结果3:", result3)

    asyncio.run(test())
