from fastapi import FastAPI, HTTPException, Query, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional, Dict, Any, Union
from pydantic import BaseModel, Field
import os
import httpx
from datetime import datetime, timedelta 
import re 

app = FastAPI(
    title="能源系统公式API",
    version="1.0.0",
    description="提供能源系统公式数据",
)

# 允许跨域请求
origins = ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class FormulaItem(BaseModel):
    name: str
    formula: str
    # displayHtml: Optional[str] = None

class FormulaResponse(BaseModel):
    energy_system_formulas: List[FormulaItem]

class FormulaCalcRequest(BaseModel):
    date: str
    time_granularity: str

class FormulaCalcResponse(BaseModel):
    value: Optional[Union[float, List[Dict[str, Any]]]] = Field(None, description="单点时间返回数值，范围时间返回数组")
    # timestamp: str


def infer_granularity(date_str: str) -> str:
    """智能推断时间粒度"""
    if re.match(r"\d{4}-\d{2}-\d{2}", date_str):
        return 'DAY'
    elif re.match(r"\d{4}-\d{2}", date_str):
        return 'MONTH'
    elif re.match(r"\d{4}", date_str):
        return 'YEAR'
    else:
        return 'dynamic'

def read_formulas():
    """读取公式文件并解析内容"""
    formulas = []
    try:
        with open(os.path.join(os.path.dirname(__file__), 'formula.txt'), 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                # 分割公式名称和公式内容
                parts = line.split(':')
                if len(parts) == 2:
                    name = parts[0].strip()
                    formula = parts[1].strip()
                    # 生成HTML显示
                    # display_html = f'<div class="formula-item"><span class="formula-name">{name}</span>: <code class="formula-content">{formula}</code></div>'
                    formulas.append(FormulaItem(
                        name=name,
                        formula=formula,
                        # displayHtml=display_html
                    ))
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"读取公式文件时发生错误: {str(e)}"
        )
    return formulas


async def parse_relative_date(
    date: str = Query(..., description="支持绝对日期(YYYY-MM-DD)、相对时间词或时间范围"),
    # time_granularity: str = Query(..., description="时间粒度")
):
    # 新增部分 例如过去几天 今天和昨天的对比这种

    # 创建基准时间（根据系统时间）
    base_date = datetime.now().date()  # 当前日期 
    base_date = datetime.combine(base_date, datetime.min.time())
    
    # 处理日期范围格式，如"2022-03到2022-05"
    date_range_pattern = r'(\d{4}-\d{2}(?:-\d{2})?)(到|至|-|/)(\d{4}-\d{2}(?:-\d{2})?)'
    match = re.search(date_range_pattern, date)
    if match:
        start_date_str = match.group(1)
        end_date_str = match.group(3)
        
        # 判断日期格式和粒度
        start_granularity = infer_granularity(start_date_str)
        end_granularity = infer_granularity(end_date_str)
        
        # 使用相同的粒度，优先使用更精细的粒度
        if start_granularity != end_granularity:
            time_granularity = 'DAY' if 'DAY' in [start_granularity, end_granularity] else ('MONTH' if 'MONTH' in [start_granularity, end_granularity] else 'YEAR')
        else:
            time_granularity = start_granularity
        
        return {
            'start_date': start_date_str,
            'end_date': end_date_str,
            'time_granularity': time_granularity,
            'is_range': True
        }
    
    # 处理时间范围表达式
    # 1. 过去X天/周/月/年
    range_patterns = [
        # 今天和昨天对比 - 特殊处理
        (r'(今天|今日)和(昨天|昨日)(对比|比较|vs|VS)', lambda m: {
            'start_date': (base_date - timedelta(days=1)).strftime("%Y-%m-%d"),
            'end_date': base_date.strftime("%Y-%m-%d"),
            'time_granularity': 'DAY',
            'is_range': True,
            'is_comparison': True
        }),
        # 昨天和今天对比 - 特殊处理
        (r'(昨天|昨日)和(今天|今日)(对比|比较|vs|VS)', lambda m: {
            'start_date': (base_date - timedelta(days=1)).strftime("%Y-%m-%d"),
            'end_date': base_date.strftime("%Y-%m-%d"),
            'time_granularity': 'DAY',
            'is_range': True,
            'is_comparison': True
        }),
        # 本月和上月对比
        (r'(本月|当月)和(上月|前月)(对比|比较|vs|VS)', lambda m: {
            'start_date': (base_date.replace(day=1) - timedelta(days=1)).replace(day=1).strftime("%Y-%m"),
            'end_date': base_date.replace(day=1).strftime("%Y-%m"),
            'time_granularity': 'MONTH',
            'is_range': True,
            'is_comparison': True
        }),
        # 今年和去年对比
        (r'(今年|本年)和(去年|上年)(对比|比较|vs|VS)', lambda m: {
            'start_date': base_date.replace(year=base_date.year-1, month=1, day=1).strftime("%Y"),
            'end_date': base_date.replace(month=1, day=1).strftime("%Y"),
            'time_granularity': 'YEAR',
            'is_range': True,
            'is_comparison': True
        }),
        # 过去X天 - 从X天前到今天
        (r'(过去|最近|近)(\d+)(天|日)', lambda m: {
            'start_date': (base_date - timedelta(days=int(m.group(2))-1)).strftime("%Y-%m-%d"),
            'end_date': base_date.strftime("%Y-%m-%d"),
            'time_granularity': 'DAY',
            'is_range': True
        }),
    ]
        # ... existing code ...

    # 检查是否匹配范围表达式
    for pattern, handler in range_patterns:
        match = re.search(pattern, date)
        if match:
            return handler(match)
    
    # 如果不是范围表达式，则按单点时间处理
    time_granularity = infer_granularity(date)

    # 预处理输入的 date 字符串，将特殊分隔符替换为统一的形式，并转换为大写
    processed_date = re.sub(r'[+_]', '', date).upper()

    # 动态匹配规则 
    relative_map = {
        r'昨日|昨天|yesterday': {
            'delta': timedelta(days=1),
            'granularity': 'DAY'
        },
        r'前日|前天|beforeyesterday': {
            'delta': timedelta(days=2),
            'granularity': 'DAY'
        },
        r'今日|今天|today': {
            'delta': timedelta(0),
            'granularity': 'DAY'
        },
        r'上月|lastmonth': {
            'calc': lambda d: (d.replace(day=1) - timedelta(days=1)).replace(day=1),
            'granularity': 'MONTH'
        },
        r'本年|thisyear': {
            'calc': lambda d: d.replace(month=1, day=1),
            'granularity': 'YEAR'
        },
        r'去年|lastyear':{
            'calc': lambda d: d.replace(year=d.year-1, month=1, day=1),
            'granularity': 'YEAR'
        },
        r'本月|当月|thismonth':{
            'calc': lambda d: d.replace(day=1),
            'granularity': 'MONTH'
        },
    }
 
    # 优先处理相对时间词 
    for pattern, rule in relative_map.items(): 
        if re.fullmatch(pattern, processed_date, re.IGNORECASE):
            if 'delta' in rule:
                target_date = base_date - rule['delta']
            else:
                target_date = rule['calc'](base_date)
            
            time_granularity = rule['granularity']
            break 
    else:
        # 处理绝对日期 
        try:
            if time_granularity == 'DAY':
                target_date = datetime.strptime(date, "%Y-%m-%d")
            elif time_granularity == 'MONTH':
                target_date = datetime.strptime(date, "%Y-%m")
            elif time_granularity == 'YEAR':
                target_date = datetime.strptime(date, "%Y")
            else:
                raise ValueError 
        except ValueError:
            raise HTTPException(400, detail=f"无效日期格式，示例：2025-04-23 / 上月 / 过去7天")
 
    format_map = {
        'DAY': "%Y-%m-%d",
        'MONTH': "%Y-%m",
        'YEAR': "%Y"
    }

    # 返回单点时间结果
    return {
        'date': target_date.strftime(format_map[time_granularity]),
        'time_granularity': time_granularity,
        'is_range': False
    } 
  
# @app.get("/get_energy_system_formulas", response_model=FormulaResponse)
# async def get_energy_system_formulas(name: str = Query(None, description="公式名称")):
#     """
#     获取能源系统公式列表
#     如果提供了公式名称，返回对应公式；否则返回所有公式
#     """
#     try:
#         formulas = read_formulas()
#         if name:
#             matched_formulas = [formula for formula in formulas if formula.name == name]
#             if not matched_formulas:
#                 raise HTTPException(
#                     status_code=404,
#                     detail=f"未找到名为 {name} 的公式"
#                 )
#             return FormulaResponse(energy_system_formulas=matched_formulas)
#         return FormulaResponse(energy_system_formulas=formulas)
#     except Exception as e:
#         raise HTTPException(
#             status_code=500,
#             detail=f"处理请求时发生错误: {str(e)}"
#         )

@app.post("/calculate_formula", response_model=FormulaCalcResponse)
async def calculate_formula(
    name: str = Query(..., description="公式名称"),
    parsed_date_info: dict = Depends(parse_relative_date),
    token: str = Query(..., description="Authorization token")
):
    """
    计算指定公式的值
    """
    try:
        # 获取公式
        formulas = read_formulas()
        formula_item = next((f for f in formulas if f.name == name), None)
        if not formula_item:
            raise HTTPException(
                status_code=404,
                detail=f"未找到名为 {name} 的公式"
            )

        # 构建请求参数
        if parsed_date_info.get('is_range') == True:
            params = {
                "endClock": parsed_date_info.get("end_date"),
                "formulas": {
                    formula_item.formula: formula_item.formula
                },
                "startClock": parsed_date_info.get("start_date"),
                "timeGranId": parsed_date_info.get("time_granularity"),
            }
        else: 
            params = {
                "expressionList": {
                    formula_item.formula: formula_item.formula
                },
                "clock": parsed_date_info.get("date"),
                "timegranId": parsed_date_info.get("time_granularity"),
            }

        # 设置请求头
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

        # 发送请求
        async with httpx.AsyncClient(timeout=30.0) as client:
            if parsed_date_info.get('is_range') == True:
                response = await client.post(
                    'http://www.shbaoenergy.com:8081/emscore/api/services/nYMC/calcData/CalcRangeValuesAsync',
                    json=params,
                    headers=headers 
                )
            else:
                response = await client.post(
                    "http://www.shbaoenergy.com:8081/emscore/api/services/nYMC/calcData/QueryItemValuesAsync",
                    json=params,
                    headers=headers
                )

            if response.status_code != 200:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"计算服务返回错误: {response.text}"
                )

            result = response.json()
            if result.get('status') != 200:
                raise HTTPException(
                    status_code=500,
                    detail=f"计算失败: {result.get('message', '未知错误')}"
                )

            # 处理范围数据和单点数据的不同返回格式
            if parsed_date_info.get('is_range') == True:
                # 范围数据返回数组
                return FormulaCalcResponse(
                    value=result.get('data', [])
                )
            else:
                # 单点数据返回数值
                return FormulaCalcResponse(
                    value=result.get('data', {}).get(formula_item.formula, 0)
                )

    except httpx.TimeoutException:
        raise HTTPException(
            status_code=504,
            detail="计算服务请求超时"
        )
    except httpx.RequestError as e:
        raise HTTPException(
            status_code=502,
            detail=f"计算服务请求错误: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"处理请求时发生错误: {str(e)}"
        )

@app.get("/health")
async def health_check():
    """
    服务健康检查接口
    """
    return {
        "status": "healthy",
        "service": "energy-system-formula-service"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)