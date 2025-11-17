# 启动程序

## 一、Windows

* [Python](https://www.python.org/downloads/windows/)最多只能使用3.12，3.13以上会报错。

* 打开开始菜单。

* 搜索 "Anaconda Prompt" 或者 "cmd"，管理员运行。

* 在 Anaconda Prompt 中运行：

  ```
  # 退出 conda 环境
  conda deactivate
  
  # 使用 Python 自带的 venv
  python -m venv ask_agent_venv
  
  #python -3.12 -m venv ask_agent_venv
  
  # 激活虚拟环境
  # Windows:
  ask_agent_venv\Scripts\activate
  # openwebui
  set HF_HUB_OFFLINE=1
  # Linux/Mac:
  # source ask_agent_venv/bin/activate
  
  :: 设置镜像源
  pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple
  
  # 安装包
  pip install -r requirements.txt
  # (ask_agent_venv) D:\gits\ask_agent\open-webui\backend>D:\gits\ask_agent\ask_agent_venv\Scripts\python.exe -m pip install -r requirements.txt
  
  # 删除旧的虚拟环境（如果有）
  rmdir /s ask_agent_venv
  
  # 先退出 venv
  deactivate
  
  # 直接使用虚拟环境中的 Python 绝对路径
  "D:\gits\ask_agent\ask_agent_venv\Scripts\python.exe" -m pip install numpy==1.24.3 pandas==1.5.3
  "D:\gits\ask_agent\ask_agent_venv\Scripts\python.exe" -m pip install torch==2.0.1 --index-url https://download.pytorch.org/whl/cpu
  "D:\gits\ask_agent\ask_agent_venv\Scripts\python.exe" -m pip install sentence-transformers==2.2.2
  # 使用绝对路径运行
  "D:\gits\ask_agent\ask_agent_venv\Scripts\python.exe" -m uvicorn main:app --host 0.0.0.0 --port 9000
  ```

* 运行

  ```
  uvicorn main_v2:app --host 0.0.0.0 --port 9001
  ```

* 脚本

  ```
  @echo off
  echo 正在设置 ask_agent 虚拟环境...
  
  :: 退出 conda 环境
  call conda deactivate
  
  :: 创建虚拟环境
  python -m venv ask_agent_venv
  
  :: 激活虚拟环境
  call ask_agent_venv\Scripts\activate
  
  :: 安装依赖
  pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple
  pip install -r requirements.txt
  
  echo 安装完成！运行以下命令启动：
  echo ask_agent_venv\Scripts\activate
  echo uvicorn main:app --host 0.0.0.0 --port 9000
  pause
  ```

* ​	创建 `run_app.bat`：

  ```
  @echo off
  cd /d "%~dp0"
  echo 启动 ask_agent 应用...
  "D:\gits\ask_agent\ask_agent_venv\Scripts\python.exe" -m uvicorn main:app --host 0.0.0.0 --port 9000
  pause
  ```

* ## 查看 requirements.txt 或环境配置

  ```
  # 查看项目中的 requirements.txt
  cat requirements.txt
  
  # 或者查看 pip 冻结的输出
  pip freeze
  
  # 生成当前环境的 requirements.txt
  pip freeze > current_versions.txt
  ```

* 最终requirements.txt

  ```
  # 核心数据科学库
  numpy==1.26.4
  pandas==2.2.3
  
  # 深度学习框架
  torch==2.8.0
  sentence-transformers==5.1.1
  
  # Web 框架
  fastapi==0.118.0
  uvicorn==0.37.0
  aiohttp==3.12.15
  httpx==0.28.1
  
  # LangChain 相关
  langchain==0.3.27
  langchain-community==0.3.29
  langchain-core==0.3.76
  langchain-text-splitters==0.3.11
  langchain-ollama==0.3.10
  
  # 文本处理
  jieba==0.42.1
  rapidfuzz==3.14.1
  
  # 工具库
  nest-asyncio==1.6.0
  python-dotenv==1.1.1
  ```

## 二、Ubuntu

## 三、Docker

```
FROM python:3.9-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "9000"]
```

很好的选择！Docker 可以确保环境一致性。我来帮你创建 Docker 配置：

### 1. 创建 Dockerfile

在你的项目根目录 `D:\gits\ask_agent\` 创建 `Dockerfile`：

dockerfile

```
FROM python:3.9-slim

WORKDIR /app

# 设置清华镜像源加速下载
RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple

# 复制依赖文件
COPY requirements.txt .

# 安装依赖
RUN pip install --no-cache-dir -r requirements.txt

# 复制项目文件
COPY . .

# 创建数据目录（如果需要）
RUN mkdir -p data models

# 暴露端口
EXPOSE 9000

# 启动命令
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "9000"]
```



### 2. 创建 requirements.txt

在项目根目录创建 `requirements.txt`：

txt

```
fastapi==0.104.1
uvicorn[standard]==0.24.0
pandas==1.5.3
numpy==1.24.3
jieba==0.42.1
rapidfuzz==3.6.1
sentence-transformers==2.2.2
torch==2.0.1
transformers==4.34.1
python-multipart==0.0.6
```



### 3. 创建 .dockerignore

创建 `.dockerignore` 文件来排除不必要的文件：

text

```
__pycache__
*.pyc
*.pyo
*.pyd
.Python
env
pip-log.txt
pip-delete-this-directory.txt
.tox
.coverage
.coverage.*
.cache
nosetests.xml
coverage.xml
*.cover
*.log
.git
.mypy_cache
.pytest_cache
.history
.DS_Store
```



### 4. 构建和运行 Docker

bash

```
# 在项目根目录执行

# 构建镜像
docker build -t ask_agent .

# 运行容器
docker run -d -p 9000:9000 --name ask_agent_container ask_agent

# 或者以交互模式运行（查看日志）
docker run -p 9000:9000 --name ask_agent_container ask_agent
```



### 5. 查看日志和管理容器

bash

```
# 查看日志
docker logs -f ask_agent_container

# 停止容器
docker stop ask_agent_container

# 启动容器
docker start ask_agent_container

# 进入容器（调试用）
docker exec -it ask_agent_container bash
```



### 6. 使用 Docker Compose（可选）

创建 `docker-compose.yml`：

yaml

```
version: '3.8'

services:
  ask_agent:
    build: .
    ports:
      - "9000:9000"
    volumes:
      - ./data:/app/data
      - ./models:/app/models
    restart: unless-stopped
    container_name: ask_agent_app
```



然后运行：

bash

```
docker-compose up -d
```



### 项目结构应该如下：

text

```
ask_agent/
├── Dockerfile
├── requirements.txt
├── .dockerignore
├── docker-compose.yml (可选)
├── main.py
├── llm_parser.py
├── tools/
│   ├── formula_api.py
│   └── platform_api.py
├── data/
└── models/
```



### 优势：

- ✅ **环境一致性**：在任何系统上运行结果相同
- ✅ **依赖隔离**：不会与主机环境冲突
- ✅ **易于部署**：一键部署到任何服务器
- ✅ **版本控制**：Dockerfile 可以版本控制

离线部署(Windows)
=========

为了 **部署 Open-WebUI**，并且 **支持未来在另外机器做离线部署**，我给你一个 **最稳、最干净、最可复制的方案**。
 避免一切“奇怪 Python 路径”“Store 版本限制”“环境不可复制”问题。

------

# 🎯 你的目标总结

- 部署 **Open-WebUI**（需要安装大量 Python 包、模型工具、依赖较复杂）
- 环境要 **稳定、可复制、可离线迁移**
- 以后可以把整个环境复制到另一台机器部署

------

# 🚀 最推荐方案（100% 适合 Open-WebUI 部署）

> **使用官方 Python + venv 虚拟环境 + pip 缓存包**
>  （绝对不要使用 Windows Store Python，不要使用 Anaconda）

------

# ⭐ 完整部署方案（强烈推荐）

## **步骤 1：卸载 Microsoft Store Python**

它会干扰各种包安装，必须卸载。

### 方法 A：设置 → 应用 → 已安装应用 → 搜索 Python → 卸载

### 方法 B（推荐）PowerShell 卸载

```
Get-AppxPackage *Python* | Remove-AppxPackage
```

卸载完成后跑：

```
where python
```

如果显示为空 or 找不到 → 成功。

------

## **步骤 2：安装官方 Python（例如 3.10 或 3.11）**

### 下载（非 Store）：

https://www.python.org/downloads/windows/

安装时务必勾选：

🟩 **Add python.exe to PATH**
 🟩 **Install Python Launcher (py.exe)**

Open-WebUI 对 Python 3.10/3.11 最兼容，强烈推荐使用：

✔ Python 3.10.x
 ✔ Python 3.11.x

（3.13 太新，会有兼容性问题）

------

## **步骤 3：创建 Open-WebUI 的独立虚拟环境**

例如你项目路径：

```
D:\gits\ask_agent\
```

进入该目录：

```
cd D:\gits\ask_agent\
```

创建虚拟环境：

```
python -m venv ask_agent_venv
```

激活：

```
ask_agent_venv\Scripts\activate
```

检验：

```
python --version
```

应该返回你安装的官方 Python 版本（3.12）。

------

## **步骤 4：安装 Open-WebUI 所需依赖（在线机器执行一次）**

```
pip install --upgrade pip
pip install -r requirements.txt
```

或如果是用官方安装脚本：

```
pip install open-webui
```

------

## **步骤 5：离线部署支持（关键步骤）**

为了做到完全离线部署：

### **Step A：把当前虚拟环境打包复制**

复制整个：

```
ask_agent_venv\
```

文件夹即可。

### **Step B：导出所有依赖列表**

```
pip freeze > requirements_freeze.txt
```

### **Step C：下载所有依赖用于离线安装**

```
pip download -r requirements_freeze.txt -d offline_packages
```

这样 `offline_packages` 目录就包含全部 `.whl`、`.tar.gz` 包。

**以后离线机器只需要：**

```
pip install --no-index --find-links=offline_packages -r requirements_freeze.txt
```

即可完全离线复现环境。

------

# 🧱 最终离线可部署的文件包括：

```
/ask_agent
    /ask_agent_venv      ← 虚拟环境（可直接复制）
    /offline_packages    ← 所有 pip 包
    requirements_freeze.txt
    config.json 或 .env
    模型文件（如有）
```

把整个目录拷贝到另一台机器就能启动。

------

# 🟢 整个过程完全避免：

- Microsoft Store Python
- Anaconda 环境污染
- 包版本冲突
- 不可复制的依赖
- WindowsApps 中奇怪的 python.exe

# ✅ **为什么 requirements_freeze.txt 里没有 open-webui？**

因为你执行的是：

```
pip install open-webui
```

但 **open-webui 是“元包”(meta-package)**，它本身不包含代码，而是安装时自动把真正的后端依赖安装进环境。

pip freeze 的输出规则：

> **只列出已安装的真实包（含版本），不列出 meta package / namespace package**

open-webui 正是这种“元包”，它的主要功能是自动安装一堆依赖，然后自身可能只包含很少或没有可安装内容。

所以 pip freeze 会列出：

✔ fastapi
 ✔ uvicorn
 ✔ langchain
 ✔ sqlalchemy
 ✔ etc…

但不会列出：

✘ open-webui（因为它只是一个安装入口，不是运行依赖）

------

# 🔧 **如何让 open-webui 出现在 requirements_freeze.txt 中？**

你可以手动加入一行：

```
open-webui
```

但是，**不推荐**，因为它不会包含具体版本信息，且 offline install 无法复原整个运行环境。

------

# ⭐ 推荐做法（最稳定，也是官方建议）

### ✅ **方式 1：用 pip freeze 导出所有真实依赖（推荐）**

```
pip freeze > requirements_freeze.txt
```

系统所有实际需要的包（真实后端环境）都会在里面，能完全复现运行环境。

你无需关心 open-webui 是否出现，因为它安装后只是一个“入口包”。

------

# ⭐ 如果你坚持让它出现（可选）

你可以手动写入版本：

### 方法 A：查版本

```
pip show open-webui
```

得到例如：

```
Version: 0.3.0
```

然后写入 requirements_freeze.txt：

```
open-webui==0.3.0
```

------

# ⭐ 但更好的办法是（官方最佳实践）

## **方式 2：使用 pip download，把 open-webui + 全部依赖一起离线打包**

```
pip download open-webui -d offline_packages
pip download -r requirements_freeze.txt -d offline_packages
```

这样 offline_packages 会包含：

- open-webui-x.x.x.whl
- 以及所有依赖的 whl，对离线部署最友好