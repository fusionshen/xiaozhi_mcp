# 启动程序

## 一、Windows

* 打开开始菜单

* 搜索 "Anaconda Prompt"

* 在 Anaconda Prompt 中运行：

  ```
  # 退出 conda 环境
  conda deactivate
  
  # 使用 Python 自带的 venv
  python -m venv ask_agent_venv
  
  # 激活虚拟环境
  # Windows:
  ask_agent_venv\Scripts\activate
  # Linux/Mac:
  # source ask_agent_venv/bin/activate
  
  :: 设置镜像源
  pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple
  
  # 安装包
  pip install -r requirements.txt
  
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
  uvicorn main:app --host 0.0.0.0 --port 9000
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