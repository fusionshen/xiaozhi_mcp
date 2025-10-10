# file: api_server.py
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware  # ← 需要这行
from pydantic import BaseModel
import pandas as pd
from io import BytesIO, StringIO
from rapidfuzz import fuzz
import dateparser
import requests
from typing import List, Optional

app = FastAPI(title="Formula Search & Invoke API")

# 允许 CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 也可以指定 http://localhost:3000 之类
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 简单内存存储（可改为 DB）
CSV_DF = None

@app.post("/upload_csv")
async def upload_csv(file: UploadFile = File(...)):
    global CSV_DF
    content = await file.read()
    try:
        # 尝试 utf-8 / gbk
        try:
            s = content.decode('utf-8')
        except:
            s = content.decode('gbk', errors='ignore')
        df = pd.read_csv(StringIO(s), dtype=str)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"csv parse error: {e}")
    CSV_DF = df.fillna('')
    return {"rows": len(CSV_DF)}

class SearchResult(BaseModel):
    RECORDID: str
    FORMULAID: str
    FORMULANAME: str
    EXPRESSION: Optional[str] = None
    SCORE: float

@app.get("/search_formula", response_model=List[SearchResult])
def search_formula(q: str, top_k: int = 5):
    """
    q: 用户自然语言问题，例如 "请给我湛江钢铁中压氧气损失率的公式"
    返回匹配度最高的公式行。
    """
    if CSV_DF is None:
        raise HTTPException(status_code=400, detail="csv not uploaded")
    candidates = []
    # 构造用于匹配的文本列
    for _, row in CSV_DF.iterrows():
        text = " ".join([
            str(row.get('FORMULANAME','')),
            str(row.get('FIELDNAME','')),
            str(row.get('FORMULAREFS','')),
            str(row.get('EXPRESSION',''))
        ])
        # 这里用快速模糊分数（也可以自己组合多个列的分数）
        score = fuzz.token_sort_ratio(q, text)
        candidates.append((score, row))
    # 排序降序
    candidates.sort(key=lambda x: x[0], reverse=True)
    res = []
    for score, row in candidates[:top_k]:
        res.append(SearchResult(
            RECORDID = row.get('RECORDID',''),
            FORMULAID = row.get('FORMULAID',''),
            FORMULANAME = row.get('FORMULANAME',''),
            EXPRESSION = row.get('EXPRESSION',''),
            SCORE = float(score)
        ))
    return res

class CallBusinessIn(BaseModel):
    formula_id: str
    expression: Optional[str] = None
    time: str  # ISO 格式或可解析格式
    extra: Optional[dict] = {}

@app.post("/call_business")
def call_business(payload: CallBusinessIn):
    """
    把公式 + 时间 调用到你的业务平台 API。
    这里给出一个示例：POST 到 business_url，body 包含 formula/expression/time
    """
    business_url = "https://your-business.example.com/api/compute"  # 请换成你实际的
    # 构建 body — 根据你业务平台接口要求调整
    body = {
        "formulaId": payload.formula_id,
        "expression": payload.expression,
        "time": payload.time,
        "extra": payload.extra
    }
    # 如果需要鉴权，在 headers 中加入 token
    headers = {"Authorization": "Bearer YOUR_TOKEN_HERE", "Content-Type": "application/json"}
    r = requests.post(business_url, json=body, headers=headers, timeout=15)
    # 直接把业务平台的响应透传
    return {"status_code": r.status_code, "resp": r.json() if r.text else r.text}

@app.get("/extract_time")
def extract_time(q: str):
    """
    简单的时间抽取：使用 dateparser 解析出第一个时间点（或时间范围）
    """
    dt = dateparser.parse(q, settings={'PREFER_DATES_FROM': 'past'})
    if not dt:
        return {"parsed": None}
    return {"parsed": dt.isoformat()}

