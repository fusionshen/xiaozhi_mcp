import json
import re
import csv
from pathlib import Path
from typing import List, Dict, Any

from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="Formula MCP Server", version="0.1")

# 假设 CSV 文件路径
CSV_FILE = Path("../FORMULAINFO_202503121558.csv")


def load_formulas() -> List[Dict[str, Any]]:
    with open(CSV_FILE, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return list(reader)


# ========== 模型输入输出定义 ==========
class SearchFormulaResponse(BaseModel):
    FORMULAID: str
    FORMULANAME: str
    EXPRESSION: str | None = None


class ExtractTimeResponse(BaseModel):
    parsed: str | None
    raw: str


class CallBusinessRequest(BaseModel):
    formula_id: str
    expression: str | None
    time: str


# ========== 功能实现 ==========
@app.get("/search_formula", response_model=List[SearchFormulaResponse])
def search_formula(q: str):
    formulas = load_formulas()
    matches = [f for f in formulas if q in f["FORMULANAME"]]
    return matches[:1]  # top1


@app.get("/extract_time", response_model=ExtractTimeResponse)
def extract_time(q: str):
    # 简化时间抽取：找 yyyy-mm 或 yyyy-mm-dd
    m = re.search(r"\d{4}-\d{2}(-\d{2})?", q)
    parsed = m.group(0) if m else None
    return {"parsed": parsed, "raw": q}


@app.post("/call_business")
def call_business(req: CallBusinessRequest):
    # 这里模拟一个业务调用
    result = {
        "formula_id": req.formula_id,
        "expression": req.expression,
        "time": req.time,
        "value": 123.45,  # 假数据
    }
    return result

