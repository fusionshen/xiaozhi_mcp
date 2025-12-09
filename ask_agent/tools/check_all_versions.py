from importlib.metadata import version

packages = [
    "numpy", "pandas", "torch", "sentence-transformers",
    "fastapi", "uvicorn", "langchain", "langchain-community",
    "langchain-core", "langchain-text-splitters", "langchain-ollama",
    "aiohttp", "httpx", "jieba", "rapidfuzz"
]

print("=== 包版本检查 ===")
for pkg in packages:
    try:
        ver = version(pkg)
        print(f"✅ {pkg}: {ver}")
    except Exception as e:
        print(f"❌ {pkg}: 未安装 ({e})")
print("=================")