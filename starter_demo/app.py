# app.py
# 上传 CSV → NL2SQL → 本地 Qwen 模型分析 → 返回结果
import pandas as pd
import streamlit as st
from langchain_community.llms import Ollama

# 初始化本地模型
llm = Ollama(model="qwen2.5:1.5b")

st.set_page_config(page_title="CSV NL2SQL Demo", page_icon="📊", layout="wide")
st.title("📊 CSV 智能问答助手 (NL2SQL + Qwen + Streamlit)")

uploaded_file = st.file_uploader("📂 上传一个 CSV 文件", type=["csv"])

if uploaded_file:
    df = pd.read_csv(uploaded_file)
    st.write("✅ 文件已加载，前5行数据预览：")
    st.dataframe(df.head())

    st.markdown("---")
    query = st.text_input("❓请输入你的问题（例如：2024年1月的平均能耗是多少？）")

    if st.button("执行查询") and query:
        # 生成 prompt
        prompt = f"""
你是一个数据分析助手，用户上传了一张表格，数据如下（前5行）：
{df.head().to_string()}

请根据用户的问题，编写一段 pandas 代码（只输出代码，不要解释），直接对名为 df 的 DataFrame 进行分析，返回最终答案。

用户问题：{query}
"""

        # 调用大模型生成 Pandas 代码
        pandas_code = llm(prompt)
        st.code(pandas_code, language="python")

        try:
            # 执行生成的 pandas 代码
            # ⚠️ 注意：这里用 exec() 执行模型返回的代码，可能需要你手动检查安全性
            local_vars = {"df": df}
            exec(pandas_code, {}, local_vars)

            # 假设模型代码里把结果存在 result 变量
            result = local_vars.get("result", None)
            if result is not None:
                st.success(f"💡 分析结果：{result}")
            else:
                st.warning("⚠️ 模型没有生成 result 变量，请检查代码。")

        except Exception as e:
            st.error(f"执行出错：{e}")

