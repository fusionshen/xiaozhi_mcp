# rag_web_multi_v2.py
# Streamlit 本地 RAG（多文件、增量入库、记忆、多轮、非阻塞）
import os
import tempfile
import hashlib
import json
import threading
import time
import streamlit as st

from langchain_community.document_loaders import PyPDFLoader, TextLoader, CSVLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import Chroma
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.llms import Ollama

# ========== 配置 ==========
EMBEDDING_MODEL = "BAAI/bge-small-zh"
DB_DIR = "./chroma_db"
PROCESSED_META = "./processed_files.json"
CHUNK_SIZE = 500
CHUNK_OVERLAP = 50
BATCH_SIZE = 64  # 每次向 Chroma 批量写入多少 chunk（可根据内存调整）
TOP_K = 3  # 检索 Top-K

# ========== 初始化 ==========
embedding_model = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)
llm = Ollama(model="qwen2.5:1.5b")

# helper: load or init processed file metadata
def load_processed_meta():
    if os.path.exists(PROCESSED_META):
        with open(PROCESSED_META, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_processed_meta(meta):
    with open(PROCESSED_META, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)

# helper: fingerprint a file
def fingerprint(path):
    stat = os.stat(path)
    token = f"{os.path.basename(path)}|{stat.st_size}|{int(stat.st_mtime)}"
    return hashlib.sha256(token.encode("utf-8")).hexdigest()

# load existing vectorstore if present
def load_vectorstore_if_exists():
    if os.path.exists(DB_DIR) and os.listdir(DB_DIR):
        try:
            vs = Chroma(persist_directory=DB_DIR, embedding_function=embedding_model)
            return vs
        except Exception as e:
            st.warning(f"加载现有向量库失败（将重建）：{e}")
            # fallthrough to None to allow rebuild
    return None

# incremental ingestion: only add chunks from new files
def ingest_files_incremental(file_paths, progress_callback=None):
    """
    file_paths: list of absolute paths to files
    progress_callback: function(progress_fraction, text) for UI updates
    """
    # ensure chroma directory exists
    os.makedirs(DB_DIR, exist_ok=True)

    processed = load_processed_meta()
    new_files = []
    for p in file_paths:
        fid = fingerprint(p)
        if fid not in processed:
            new_files.append((p, fid))
    if not new_files:
        if progress_callback:
            progress_callback(1.0, "没有新文件需要导入。")
        return

    # Load or create vectorstore object
    vectorstore = load_vectorstore_if_exists()
    if vectorstore is None:
        # create empty Chroma by writing zero items via from_texts([])
        vectorstore = Chroma.from_texts([], embedding_model, persist_directory=DB_DIR)

    splitter = RecursiveCharacterTextSplitter(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)
    total_chunks = 0
    chunks_buffer = []

    # iterate files and chunk them
    for file_idx, (file_path, fid) in enumerate(new_files):
        ext = os.path.splitext(file_path)[1].lower()
        if ext == ".pdf":
            loader = PyPDFLoader(file_path)
        elif ext == ".csv":
            loader = CSVLoader(file_path, encoding="utf-8")
        else:
            loader = TextLoader(file_path, encoding="utf-8")
        docs = loader.load()
        chunks = splitter.split_documents(docs)
        total_chunks += len(chunks)
        # for each chunk add metadata about source file and chunk index
        for i, c in enumerate(chunks):
            meta = {"source": os.path.basename(file_path), "file_fingerprint": fid, "chunk_index": i}
            chunks_buffer.append((c.page_content, meta))

        # flush buffer periodically to control memory/CPU bursts
        while len(chunks_buffer) >= BATCH_SIZE:
            batch = chunks_buffer[:BATCH_SIZE]
            texts = [t for t, m in batch]
            metadatas = [m for t, m in batch]
            # add_texts will compute embeddings then persist
            vectorstore.add_texts(texts=texts, metadatas=metadatas)
            # remove flushed
            chunks_buffer = chunks_buffer[BATCH_SIZE:]
            if progress_callback:
                progress_callback(0.01, f"已写入部分块到向量库（已写入若干批次）...")

        # mark file processed
        processed[fid] = {
            "filename": os.path.basename(file_path),
            "size": os.path.getsize(file_path),
            "mtime": int(os.path.getmtime(file_path))
        }
        save_processed_meta(processed)

    # flush remaining
    if chunks_buffer:
        texts = [t for t, m in chunks_buffer]
        metadatas = [m for t, m in chunks_buffer]
        vectorstore.add_texts(texts=texts, metadatas=metadatas)

    # persist Chroma
    if hasattr(vectorstore, "persist"):
        vectorstore.persist()

    if progress_callback:
        progress_callback(1.0, f"导入完成：共导入 {total_chunks} 个块。")

# RAG query: returns (quick_snippet, llm_answer_or_none)
def rag_query_with_quick_snippet(query, vectorstore, history=None, run_llm=False):
    """
    - quick_snippet: top-1 doc snippet (fast)
    - llm_answer: if run_llm True, call LLM with context and return full answer; else None
    """
    # fast similarity search (should be quick if vectorstore loaded)
    docs = vectorstore.similarity_search(query, k=TOP_K)
    if not docs:
        return ("未检索到相关片段。", None)

    quick_snippet = docs[0].page_content[:500]  # 500 chars as quick preview

    llm_answer = None
    if run_llm:
        # prepare prompt including chat history (memory)
        history_text = ""
        if history:
            for q, a in history[-6:]:  # 最近6轮
                history_text += f"用户：{q}\n助手：{a}\n"
        context = "\n\n".join([f"[来源：{d.metadata.get('source','unknown')}] {d.page_content}" for d in docs])
        prompt = f"""
你是企业知识助手。下面是相关文档片段与对话历史，请基于这些内容回答用户问题，回答时给出引用来源（文件名）。
对话历史：
{history_text}

相关文档片段：
{context}

用户问题：{query}

请基于文档回答，如果文档中没有，请说明“文档未涉及”。"""
        llm_answer = llm(prompt)
    return quick_snippet, llm_answer

# ========== Streamlit UI ==========
st.set_page_config(page_title="本地 RAG（增量+多文件+记忆）", layout="wide")
st.title("📘 本地 RAG 知识助手（增量入库 + 多文件 + 记忆）")

# show status of existing vector DB
vectorstore = load_vectorstore_if_exists()
if vectorstore:
    st.info("已加载本地向量库（可立即检索）")
else:
    st.info("当前没有本地向量库，上传文件后将构建第一个向量库（可增量导入）")

# Session memory for chat history
if "history" not in st.session_state:
    st.session_state["history"] = []  # list of (question, answer)

# file uploader (multiple)
uploaded_files = st.file_uploader("📂 上传多个文件 (PDF / TXT / CSV)", accept_multiple_files=True, type=["pdf", "txt", "csv"])

# place to show ingestion progress
progress_text = st.empty()
prog_bar = st.progress(0.0)

# ingestion thread control
if uploaded_files:
    # write uploaded files to temp paths
    tmp_paths = []
    for uf in uploaded_files:
        suffix = os.path.splitext(uf.name)[1]
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(uf.read())
            tmp_paths.append(tmp.name)

    # define progress callback for background ingestion
    def progress_cb(fraction, text):
        prog_bar.progress(min(max(fraction, 0.0), 1.0))
        progress_text.text(text)

    # kick off a background thread to ingest files incrementally
    ingest_thread = threading.Thread(target=ingest_files_incremental, args=(tmp_paths, progress_cb))
    ingest_thread.daemon = True
    ingest_thread.start()
    st.success("已开始后台导入文件。现有向量库可继续被查询；新文件导入完成后会自动可用。")

# Query area
st.markdown("---")
st.subheader("问答区（即时片段 + 可选全文生成）")
query = st.text_input("❓ 请输入你的问题（多轮会话会保留历史上下文）")

col1, col2 = st.columns([1, 1])
with col1:
    if st.button("快速检索（秒级，返回 Top-1 片段）"):
        # ensure vectorstore exists (load again in case background finished)
        vectorstore = load_vectorstore_if_exists()
        if not vectorstore:
            st.error("当前没有可用向量库，请先上传文件并等待导入完成。")
        else:
            quick, _ = rag_query_with_quick_snippet(query, vectorstore, history=st.session_state["history"], run_llm=False)
            st.markdown("**快速片段（预览）**")
            st.write(quick)

with col2:
    if st.button("生成完整答案（可能 >10s）"):
        vectorstore = load_vectorstore_if_exists()
        if not vectorstore:
            st.error("当前没有可用向量库，请先上传文件并等待导入完成。")
        else:
            with st.spinner("正在调用模型生成完整答案，可能耗时..."):
                quick, full = rag_query_with_quick_snippet(query, vectorstore, history=st.session_state["history"], run_llm=True)
            if full:
                st.markdown("### 💡 完整答案")
                st.write(full)
                # record to history
                st.session_state["history"].append((query, full))
            else:
                st.write("未生成完整答案，展示快速片段：")
                st.write(quick)

# show chat history (memory)
if st.session_state["history"]:
    st.markdown("---")
    st.subheader("会话历史（记忆）")
    for i, (q, a) in enumerate(reversed(st.session_state["history"][-20:])):
        st.markdown(f"**Q:** {q}")
        st.write(f"**A:** {a}")

