# rag_sql_web.py
# 混合 Demo：表格型 CSV → NL2SQL (DuckDB) ; 文本型文档 → RAG (Chroma)
# 本地模型：Ollama + Qwen2.5

import os
import tempfile
import duckdb
import pandas as pd
import streamlit as st

from langchain_community.document_loaders import PyPDFLoader, TextLoader, CSVLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_chroma import Chroma
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.llms import Ollama
from langchain.prompts import PromptTemplate

# ========== Step 1: 全局配置 ==========
DB_DIR = "./chroma_db"
EMBEDDING_MODEL = "BAAI/bge-small-zh"
embedding = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)
llm = Ollama(model="qwen2.5:1.5b")  # 本地大模型

# DuckDB 连接（内存中）
duck_con = duckdb.connect()

# ========== Step 2: 文档 → 向量库 ==========
def build_vectorstore(file_path):
    if file_path.endswith(".pdf"):
        loader = PyPDFLoader(file_path)
    else:
        loader = TextLoader(file_path, encoding="utf-8")
    docs = loader.load()

    splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
    chunks = splitter.split_documents(docs)

    texts = [c.page_content for c in chunks]
    vectorstore = Chroma.from_texts(texts, embedding=embedding, persist_directory=DB_DIR)
    vectorstore.persist()
    return vectorstore

def rag_query(query, vectorstore):
    docs = vectorstore.similarity_search(query, k=3)
    context = "\n".join([d.page_content for d in docs])
    prompt = f"""你是企业知识助手。以下是相关文档片段：
{context}

问题：{query}
请基于文档内容回答，如果文档中没有，请说明“文档未涉及”。"""
    return llm(prompt)

# ========== Step 3: CSV → NL2SQL (DuckDB) ==========
def load_csv_to_duckdb(file_path, table_name="mytable"):
    df = pd.read_csv(file_path)
    duck_con.register(table_name, df)
    return df.head()  # 返回前几行用于展示

def sql_query(question, table_name="mytable"):
    # 用 LLM 把问题转 SQL
    prompt_template = PromptTemplate(
        input_variables=["question", "table"],
        template="""
你是 SQL 专家。用户会提一个自然语言问题，请你只生成 SQL 查询语句，不要解释。

问题：{question}
数据表：{table}

请生成 DuckDB SQL：
"""
    )
    sql_prompt = prompt_template.format(question=question, table=table_name)
    sql_code = llm(sql_prompt)

    try:
        result = duck_con.execute(sql_code).df()
        return result, sql_code
    except Exception as e:
        return f"SQL 执行错误: {e}\n生成的 SQL: {sql_code}", sql_code

# ========== Step 4: Streamlit Web 界面 ==========
st.set_page_config(page_title="RAG + NL2SQL Demo", layout="wide")
st.title("📘 混合知识助手：RAG + NL2SQL")

uploaded_file = st.file_uploader("上传文档（CSV / PDF / TXT）", type=["csv", "pdf", "txt"])

if uploaded_file:
    with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(uploaded_file.name)[1]) as tmp_file:
        tmp_file.write(uploaded_file.read())
        tmp_path = tmp_file.name

    if uploaded_file.name.endswith(".csv"):
        st.info("📊 检测到 CSV 文件，走 NL2SQL 路径")
        df_preview = load_csv_to_duckdb(tmp_path)
        st.write("数据预览：", df_preview)

        question = st.text_input("请输入你的问题（自动转 SQL）")
        if question:
            result, sql_code = sql_query(question)
            st.code(sql_code, language="sql")
            st.write("查询结果：", result)

    else:
        st.info("📄 检测到文本文档，走 RAG 路径")
        vectorstore = Chroma(persist_directory=DB_DIR, embedding_function=embedding)
        if not vectorstore.get()["_collection"].count():
            st.warning("⚠️ 知识库为空，正在构建...")
            vectorstore = build_vectorstore(tmp_path)
            st.success("✅ 已构建知识库")

        query = st.text_input("请输入你的问题（基于文档检索回答）")
        if query:
            answer = rag_query(query, vectorstore)
            st.write("💡 答案：", answer)

