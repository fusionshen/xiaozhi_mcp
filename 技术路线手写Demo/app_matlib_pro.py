# rag_web_demo.py
# Streamlit 版本地 RAG Demo：支持 PDF / TXT / CSV 文件

import streamlit as st
from langchain_community.document_loaders import PyPDFLoader, TextLoader, CSVLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.vectorstores import Chroma
from sentence_transformers import SentenceTransformer
from langchain_community.llms import Ollama
import os
import tempfile

# ========== Step 1: 初始化 ==========
EMBEDDING_MODEL = "BAAI/bge-small-zh"  # 中文向量模型
DB_DIR = "./chroma_db"

# 嵌入模型（文本转向量）
embedding_model = SentenceTransformer(EMBEDDING_MODEL)

# Ollama 本地模型（已装好 qwen2.5-1.5b）
llm = Ollama(model="qwen2.5:1.5b")

# ========== Step 2: 构建向量库 ==========
def build_vectorstore(file_path):
    if file_path.endswith(".pdf"):
        loader = PyPDFLoader(file_path)
    elif file_path.endswith(".csv"):
        loader = CSVLoader(file_path, encoding="utf-8")
    else:
        loader = TextLoader(file_path, encoding="utf-8")

    docs = loader.load()
    splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
    chunks = splitter.split_documents(docs)

    texts = [c.page_content for c in chunks]
    vectorstore = Chroma.from_texts(texts, embedding_model, persist_directory=DB_DIR)
    vectorstore.persist()

# ========== Step 3: RAG 查询 ==========
def rag_query(query):
    vectorstore = Chroma(persist_directory=DB_DIR, embedding_function=embedding_model)
    docs = vectorstore.similarity_search(query, k=3)
    context = "\n".join([d.page_content for d in docs])

    prompt = f"""你是企业知识助手。以下是相关文档片段：
{context}

问题：{query}
请基于文档内容回答，如果文档中没有，请说明“文档未涉及”。"""

    response = llm(prompt)
    return response

# ========== Step 4: Streamlit 界面 ==========
st.set_page_config(page_title="📘 本地 RAG 知识助手", layout="wide")

st.title("📘 本地 RAG 知识助手")
st.write("上传 PDF / TXT / CSV 文件，构建知识库，然后提问。")

# 文件上传
uploaded_file = st.file_uploader("上传文件", type=["pdf", "txt", "csv"])
if uploaded_file is not None:
    with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(uploaded_file.name)[-1]) as tmp_file:
        tmp_file.write(uploaded_file.read())
        tmp_path = tmp_file.name
    build_vectorstore(tmp_path)
    st.success("✅ 已构建知识库")

# 提问
query = st.text_input("❓请输入你的问题：")
if query:
    answer = rag_query(query)
    st.markdown(f"### 💡 答案：\n{answer}")

