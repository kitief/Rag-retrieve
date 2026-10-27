# RagVault

> 自托管 · RAG 驱动的 AI 学习系统 · 云端 LLM + 本地向量化
>
> **版本 `alpha-v1.3`** · 仓库地址：<https://github.com/kitief/Rag-retrieve>
>
> 简体中文 | [English](README.en.md)

一个面向学生的自托管检索增强生成（RAG）学习平台。上传 PDF 和 PPTX 文件即可创建「知识空间」，随后可以进行提问、生成测验、创建 AI 学习笔记、追踪薄弱知识点，并获得个性化学习建议。

所有**答案生成**都通过 OpenAI 兼容接口交给云端 LLM 完成（默认使用 **DeepSeek**，也支持任何兼容端点）。**向量化则全程在本地完成**，由 FastEmbed ONNX 负责，因此你的文档只会在本机被转换成向量 —— 只有检索命中的片段会发送给模型服务商。

---

## ⚡ 快速开始

### 环境要求

| 工具 | 版本 | 说明 |
|------|---------|-------|
| Docker | 24.0+ | |
| Docker Compose | 2.20+ | |
| 内存 | 最低 8GB | Postgres + Chroma + 后端 + 前端 |
| 磁盘 | 3GB 可用空间 | Python + Node 镜像及数据卷 |
| LLM API Key | — | DeepSeek：https://platform.deepseek.com/api_keys |

### 1. 克隆并配置

```bash
git clone https://github.com/kitief/Rag-retrieve.git
cd Rag-retrieve
cp .env.example .env
```

编辑 `.env`，至少需要填写：

```bash
POSTGRES_PASSWORD=your_strong_password
JWT_SECRET=your_random_32_char_secret_here
LLM_API_KEY=sk-...            # 必填 —— 对话、测验、笔记全都依赖它
LLM_PROVIDER=deepseek         # 或：openai | custom
```

如果你使用的不是 DeepSeek，还需要额外设置：

```bash
LLM_BASE_URL=https://your-endpoint/v1
LLM_MODEL=your-model-name
```

### 2. 启动所有服务

```bash
docker compose up -d
```

该命令会启动 **4 个服务**：`postgres`、`chromadb`、`backend`、`frontend`。
没有本地模型服务，也不会下载 GGUF 模型。

### 3. 打开应用

```
http://localhost:3000
```

注册账号、创建知识空间、上传文档，然后就可以开始学习了！

> ⚠️ 运行时需要联网（用于调用 LLM 服务商接口）；首次启动时也需要联网，以便拉取 Docker 镜像和 FastEmbed ONNX 模型。

---

## 🖥 Windows 桌面版

除了 Docker 部署，本仓库还可以打包成**免 Docker、免 Python 环境的 Windows 桌面应用**：
双击安装，后端（PyInstaller 冻结的 FastAPI + SQLite + 嵌入式 Chroma）由 Tauri 壳自动拉起，
界面在原生 WebView2 窗口里运行。

**安装包**：`src-tauri/target/release/bundle/nsis/RagVault_1.3.0_x64-setup.exe`（约 137 MiB）

安装位置为 `%LOCALAPPDATA%\RagVault`（无需管理员权限），用户数据在 `%APPDATA%\RagVault`。

> **首次运行**：安装包未做代码签名，Windows SmartScreen 会提示「已保护你的电脑」。
> 点「更多信息」→「仍要运行」；或对安装包右键 → 属性 → 勾选「解除锁定」再装。

**从源码构建**（需要 Rust MSVC 工具链 + Python 3.11 + Node 20+）：

```powershell
# 1) 前端
cd frontend; npm run build
# 2) 冻结后端（约 5 分钟，产物 321 MB）
.venv-desktop\Scripts\pyinstaller backend\ragvault-backend.spec
# 3) 重新同步前端 bundle 进冻结产物（tauri 不会替你重打包）
Copy-Item frontend\dist\* dist\ragvault-backend\_internal\frontend\dist\ -Recurse -Force
# 4) 打安装包（首次需代理下载 NSIS）
$env:https_proxy="http://127.0.0.1:7897"
frontend\node_modules\.bin\tauri build
```

完整的设计权衡、踩坑记录与验收清单见
[docs/desktop-packaging.md](docs/desktop-packaging.md)。

桌面版与 Docker 版的差异：

| | Docker 版 | 桌面版 |
| --- | --- | --- |
| 数据库 | PostgreSQL | SQLite（WAL） |
| 向量库 | ChromaDB Server | 嵌入式 Chroma（PersistentClient） |
| 启动 | `docker compose up -d` | 双击 exe |
| 数据位置 | Docker 卷 | `%APPDATA%\RagVault` |
| 资源上传上限 | 2 GB | 500 MB |
| 访问方式 | 浏览器 `localhost:3000` | 原生窗口 |

---

## 🏗 架构

```
浏览器 (React + Vite)
   │  REST + SSE  │
   ▼               ▼
FastAPI 后端 (端口 8000)
   ├── 认证 (JWT)
   ├── 摄取服务
   │    └── PDF/PPTX/Word/TXT/MD/图片/音视频 → 解析 → 分块 → 向量化 → ChromaDB
   ├── RAG 服务 (LangGraph)
   │    └── 提问 → 向量化 → 检索 → LLM → 答案 + 引用  (SSE 流式)
   ├── 测验服务
   │    └── LLM 并行分批生成选择题 → 评分 → 薄弱知识点
   ├── 笔记服务
   │    └── LLM 逐页生成学习卡片 → 可下载 PDF
   └── 推荐服务
        └── LangGraph → LLM → 个性化 Markdown 学习计划
   │
   ├── PostgreSQL（用户、会话、消息、文档、测验、笔记）
   ├── ChromaDB 0.5.18（向量嵌入，每个 chat_id 一个 collection）
   └── 云端 LLM（OpenAI 兼容的 Chat Completions 接口 —— 默认 DeepSeek）
```

### LLM 服务商

`backend/app/services/llm_client.py` 是与模型服务商通信的唯一入口。它使用
OpenAI Chat Completions 协议，并内置了一张服务商预设表：

| `LLM_PROVIDER` | 默认 Base URL | 默认模型 | 密钥环境变量 |
|---|---|---|---|
| `deepseek` | `https://api.deepseek.com/v1` | `deepseek-chat` | `LLM_API_KEY` |
| `openai` | `https://api.openai.com/v1` | `gpt-4o-mini` | `LLM_API_KEY` |
| `custom` | *（取自 `LLM_BASE_URL`）* | *（取自 `LLM_MODEL`）* | `LLM_API_KEY` |

显式设置的 `LLM_BASE_URL` / `LLM_MODEL` 始终优先于预设值，因此任何
OpenAI 兼容网关（Azure OpenAI、Moonshot、Qwen、自建的 vLLM……）只要设置
`LLM_PROVIDER=custom` 即可接入。

功能特性：对话 SSE 的 token 流式输出、笔记生成器使用的
`response_format=json_object`、遇到 429/5xx 时自动按指数退避重试，以及一个
启动探测 —— 密钥缺失时只记录警告（API 仍能正常启动，`/health` 保持绿色）。

> 旧的本地栈（`model-init` + `llm` llama.cpp 服务、`app/utils/ollama_helper.py`、
> `app/services/llm_gate.py`、LangChain 的 `Ollama` 客户端）已被移除。
> `scripts/setup_model.py` 和 `models/*.gguf` 已不再被 compose 使用。

---

## 🌐 多语言（English / 简体中文）

用户能看到的一切 —— Web 界面、校验错误信息、以及模型写出的答案 —— 都可以在
**English** 和 **简体中文** 之间切换。

### 部署级默认语言

在 `.env` 中设置 `APP_LANGUAGE` 并重启后端：

```env
APP_LANGUAGE=zh     # zh = 简体中文，en = English（默认）
```

`docker-compose.yml` 会把它透传给后端容器。该值通过 `GET /config`
（`default_language` 字段）暴露给浏览器，因此全新浏览器首次打开应用时就会使用该语言。

### 单个访问者覆盖

语言切换器位于侧边栏底部，紧挨着深色/浅色切换按钮（侧边栏变窄时会收成一个地球图标按钮）。
在此处做出的选择会存入 `localStorage`（`ragvault-language-preference`），并且仅对该浏览器生效，
优先级高于 `APP_LANGUAGE` —— 这对共用机器、或需要同时演示两种语言的场景很方便。

### 语言如何传递到后端

1. `src/api/client.ts` 为每个 axios 请求加上 `X-App-Language: en|zh` 请求头，
   `src/api/messages.ts` 对 SSE 的 `fetch` 也做同样处理，因此流式答案会跟随界面语言。
2. `app/main.py` 用 `LanguageMiddleware` 包裹 ASGI 应用，把请求头的值存入
   `contextvars.ContextVar`（这是一个裸 ASGI 中间件，因此该值在流式响应体
   被消费期间仍然有效）。
3. `app/core/i18n.py` 按请求解析语言
   （`X-App-Language` → `APP_LANGUAGE` → `en`），并提供：
   - `t("chat.not_found")` 用于 API 错误详情，
   - `prompt_language_directive()` 追加到每个 LLM 提示词中，让模型用当前语言
     作答（提示词本身保持英文），
   - 语言感知的 PDF 导出：笔记 PDF 使用 PyMuPDF 的 `Story` 引擎排版，
     该引擎会按宽度折行 CJK 文本，并对中文字形回退到内置字体
     （内置的 Helvetica 没有中文字形），随后对嵌入字体做子集化，
     使一页摘要的体积保持在 30 KB 左右。

跨请求不做任何缓存，因此两个浏览器可以同时使用不同语言。

### 新增一种语言

1. 在 `frontend/src/i18n/index.ts` 的 `SUPPORTED_LANGUAGES` 中加入语言代码
   （并在 `backend/app/core/i18n.py` 的 `SUPPORTED_LANGUAGES` 中同步添加）。
2. 复制 `frontend/src/i18n/messages.ts` 中的 `zh` 表并翻译 ——
   如果有键缺失，`tsc` 会直接报错，因为 `zh` 的类型是
   `Record<MessageKey, string>`。
3. 复制 `backend/app/core/i18n.py` 中的 `zh` 代码块；并往
   `useDateLocale()` 中放入对应的 date-fns 语言包。

---

## 📁 支持的文件类型

| 类型 | 扩展名 | 状态 | 处理方式 |
|------|-----------|--------|------------|
| PDF | `.pdf` | ✅ 已启用 | PyMuPDF 逐页解析；仅当 `ENABLE_OCR_UPLOADS=true` 时扫描页才回退到 OCR |
| PowerPoint | `.pptx` `.ppt` | ✅ 已启用 | python-pptx 逐张幻灯片解析；二进制 `.ppt` 通过原始流提取作为回退 |
| Word | `.docx` `.doc` | 🅿️ 已搁置 | python-docx / ZIP-XML 回退 —— 解析器保留，但上传会被拒绝 |
| 纯文本 | `.txt` `.md` `.csv` | 🅿️ 已搁置 | 直接读取，切分为约 2000 字符的伪页面 —— 解析器保留 |
| 图片 | `.png` `.jpg` `.jpeg` `.webp` `.bmp` `.tiff` | 🅿️ 已搁置 | Tesseract OCR + 对比度增强 —— 需 `ENABLE_OCR_UPLOADS=true` |
| 视频 | `.mp4` `.mkv` `.mov` `.avi` `.webm` | 🅿️ 已搁置 | ffmpeg 抽取音轨 → Faster-Whisper —— 需 `ENABLE_AUDIO_VIDEO_UPLOADS=true` |
| 音频 | `.mp3` `.wav` `.m4a` `.ogg` `.flac` `.aac` | 🅿️ 已搁置 | Faster-Whisper（PyAV 回退） —— 需 `ENABLE_AUDIO_VIDEO_UPLOADS=true` |

> ❌ 任何不在已启用列表中的类型都会被拒绝，并返回清晰的 422 错误信息。
> 📦 单文件最大上传体积：**2 GB**。

### 重新启用已搁置的解析器

解析代码**完整保留**在 `backend/app/utils/parsers.py`；只是入口被开关挡住了。
要恢复某一种：

1. 在 `.env` 中设置 `ENABLE_OCR_UPLOADS=true` 和/或 `ENABLE_AUDIO_VIDEO_UPLOADS=true`
2. 在 `backend/requirements.txt` 中取消注释 `pytesseract` / `faster-whisper`
3. 在 `backend/Dockerfile` 中取消注释 `tesseract-ocr` / `ffmpeg` 的 `apt-get` 代码块
4. （可选）把扩展名加回 `frontend/src/components/documents/DropZone.tsx`
   的 `SUPPORTED_EXTS`

---

## 🖥 技术栈

| 层级 | 技术 |
|-------|-----------|
| 前端 | React 18 + Vite + TypeScript + Tailwind CSS + shadcn/ui |
| 动画 | Framer Motion + Three.js |
| 状态管理 | TanStack Query v5 + Zustand v5 |
| 后端 | FastAPI + LangGraph |
| LLM | **云端 API**，走 OpenAI 兼容的 Chat Completions（默认 DeepSeek） |
| 默认模型 | `deepseek-chat`（可通过 `LLM_PROVIDER` / `LLM_MODEL` 配置） |
| 向量化 | **FastEmbed**（ONNX Runtime）—— `BAAI/bge-small-en-v1.5` |
| 向量数据库 | ChromaDB 0.5.18（本地持久化） |
| 关系型数据库 | PostgreSQL 16 |
| 语音转文字 | *已搁置* —— Faster-Whisper 代码保留，默认禁用 |
| OCR | *已搁置* —— Tesseract 代码保留，默认禁用 |
| 认证 | JWT（access + refresh 双 token），bcrypt |
| 部署 | Docker + Docker Compose |

实现完全遵循上述技术栈，未作任何偏离。

---

## ⚙️ 配置

所有配置都在 `.env` 中。关键变量：

| 变量 | 默认值 | 说明 |
|----------|---------|-------------|
| `LLM_PROVIDER` | `deepseek` | `deepseek` / `openai` / `custom` |
| `LLM_API_KEY` | *（必填）* | 服务商 API 密钥 —— 对话、测验、笔记、标题生成都需要 |
| `LLM_MODEL` | `deepseek-chat` | 发送给服务商的模型标识 |
| `LLM_BASE_URL` | `https://api.deepseek.com/v1` | OpenAI 兼容的 base URL（覆盖预设值） |
| `LLM_TIMEOUT_SECONDS` | `180` | 单请求超时时间 |
| `LLM_MAX_RETRIES` | `3` | 遇到 429 / 5xx / 传输错误时的重试次数 |
| `APP_LANGUAGE` | `en` | 部署级默认界面与 AI 语言（`en` / `zh`） |
| `ENABLE_AUDIO_VIDEO_UPLOADS` | `false` | 已搁置的音频/视频转写 |
| `ENABLE_OCR_UPLOADS` | `false` | 已搁置的图片 / 扫描版 PDF OCR |
| `EMBEDDING_MODEL` | `BAAI/bge-small-en-v1.5` | FastEmbed ONNX 向量化模型 |
| `WHISPER_MODEL` | `base` | 仅在重新启用音频/视频时使用 |
| `CHUNK_SIZE` | `600` | 每个文本块的目标 token 数 |
| `CHUNK_OVERLAP` | `100` | 相邻文本块之间的 token 重叠 |
| `TOP_K` | `5` | 每次查询检索的文本块数量 |
| `WHISPER_DEVICE` | `cpu` | 有 GPU 时可设为 `cuda` |
| `POSTGRES_PASSWORD` | *（必填）* | PostgreSQL 密码 |
| `JWT_SECRET` | *（必填）* | 用于 JWT 签名的 32 位以上随机字符串 |

---

## 🚀 使用指南

### 创建知识空间

1. 点击侧边栏的 **“+ New Chat”**
2. 给它起个名字（例如“机器学习期末复习”）
3. 通过拖拽或点击浏览上传你的文档

### 与文档对话

- 在聊天框输入问题，按 **Enter** 或 **Ctrl+Enter** 发送
- 答案通过 SSE 实时逐 token 流式输出，并附带来源引用（文件名 + 页码）
- 引用严格有据 —— LLM 无法凭空捏造来源

### 生成测验

1. 打开右侧面板的 **Quiz** 标签页
2. 输入主题（例如“神经网络”）并选择题目数量
3. 点击 **Generate Quiz** —— LLM 会从相关文档片段中并行分批生成选择题
4. 提交答案后可查看得分、解析和薄弱知识点
5. 点击 **Get Recommendations**，基于你最近 5 次测验结果获得个性化的 Markdown 学习计划

### AI 笔记

1. 打开右侧面板的 **Notes** 标签页
2. 点击 **Generate Notes** —— LLM 会为所有已上传文档生成结构化的逐页学习卡片
3. 通过 PDF 下载按钮导出为**可搜索的 PDF**
4. 提交测验后，可以生成**补救笔记**，只针对你答错的概念（同样可下载为 PDF）

### 添加更多文档

向已有会话上传新文档 —— 它们会累加进知识库。使用 **“Clear Knowledge”** 可在不删除会话的前提下清空全部向量并重新开始。

### 重命名或删除知识空间

- 首次提问后，会话会自动用 LLM 生成标题
- 可通过 PATCH 会话接口或界面进行重命名
- 删除会话（会连同消息、文档、测验、笔记及向量库一并清除）

---

## 🛠 开发环境搭建

```bash
# 后端（Python 3.11）
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload

# 前端（Node 20）
cd frontend
npm install
npm run dev
```

后端运行在 `http://localhost:8000`，前端运行在 `http://localhost:3000`（并通过代理指向后端）。

---

## ⚙️ 应用内设置

点击侧边栏底部的头像（或按 `Ctrl+,`）即可打开设置对话框。它包含两组设置：

| 分组 | 作用 |
| --- | --- |
| **Language（语言）** | 为当前浏览器在 English 和 中文之间切换界面、校验信息和 AI 答案。勾选 `Use as deployment default` 还会把该选择存为所有新访问者的默认值。 |
| **API** | 从下拉框选择服务商（DeepSeek / OpenAI / 任何 OpenAI 兼容端点），然后设置 API 密钥、base URL 和模型。模型字段是一个从该端点 `GET /v1/models` 动态填充的下拉框，并保留手动输入的兜底方式。`Test connection` 会在不保存的前提下探测端点连通性。 |

### 已保存的 API 密钥

**API** 面板维护着一个小型密钥库（`llm_api_keys` 表），让多组凭据可以共存并随时切换，无需反复输入：

| 操作 | 效果 |
| --- | --- |
| 输入密钥 + 标签 → **Save key** | 保存该密钥并立即启用 |
| **Saved keys** 下拉框 | 切换当前生效的凭据；该选择对下一个请求即刻生效 |
| 垃圾桶图标 | 删除当前生效的密钥 |

同一时刻只有一个密钥处于生效状态 —— 它会被同步到 `app_settings.llm_api_key`，
这样请求链路就只需一次字典查找。密钥在 API 上是只写的：
响应中只会出现诸如 `sk-…1a2b` 这样的掩码提示。

这些值存放在 `app_settings` 表中，因此它们**能跨重启保留，并覆盖 `.env` 中的对应项**
—— 无需重新构建镜像。只有检索到的文档片段会发送给服务商；向量化始终留在本地。

对话框底部的 `Restore defaults` 会删除所有已存储的覆盖项，使 `.env` 配置重新生效。

---

## 🧪 运行测试

测试套件不属于运行时镜像，因此需要先安装额外依赖：

```bash
# 后端测试
cd backend
pip install pytest pytest-asyncio aiosqlite
pytest tests/ -v --tb=short

# 前端 lint
cd frontend
npm run lint
```

`backend/tests/conftest.py` 中的 fixture 使用内存 SQLite，因此不需要
PostgreSQL 或 ChromaDB 实例。

---

## 🔧 服务管理

```bash
# 查看日志
docker compose logs -f backend

# 重启某个服务
docker compose restart backend

# 完整停止（保留数据卷）
docker compose down

# 完整停止 + 删除所有数据
docker compose down -v
```

### 可选：Nginx 反向代理

`docker-compose.yml` 中定义了一个 Nginx 服务，但被 Docker Compose profile 挡住了。要启用它：

```bash
docker compose --profile nginx up -d
```

Nginx 会在 80 端口提供服务，并同时反向代理后端和前端。

---

## 📊 API 参考

启动后，API 文档可在 `http://localhost:8000/docs`（Swagger UI）和 `http://localhost:8000/redoc` 查看。

**核心接口：**

| 方法 | 路径 | 说明 |
|--------|------|-------------|
| `POST` | `/auth/register` | 注册新用户 |
| `POST` | `/auth/login` | 登录，获取 JWT token |
| `GET` | `/chats` | 列出所有知识空间 |
| `POST` | `/chats` | 创建新知识空间 |
| `GET` | `/chats/{id}` | 获取单个知识空间 |
| `PATCH` | `/chats/{id}` | 重命名知识空间 |
| `DELETE` | `/chats/{id}` | 删除知识空间（清除所有数据） |
| `POST` | `/chats/{id}/documents` | 上传并摄取文档（异步，返回 202） |
| `GET` | `/chats/{id}/documents` | 列出文档及其处理状态 |
| `DELETE` | `/chats/{id}/documents/{doc_id}` | 删除单个文档及其向量 |
| `POST` | `/chats/{id}/messages` | 提问（SSE 流式或 JSON） |
| `GET` | `/chats/{id}/messages` | 获取聊天历史 |
| `DELETE` | `/chats/{id}/messages` | 清空所有消息 |
| `DELETE` | `/chats/{id}/messages/{msg_id}` | 删除单条消息 |
| `POST` | `/chats/{id}/quiz` | 生成测验（从文档出选择题） |
| `GET` | `/chats/{id}/quiz-history` | 列出某个空间的所有历史测验 |
| `POST` | `/quiz/{id}/submit` | 提交测验答案，获取得分 + 薄弱知识点 |
| `GET` | `/chats/{id}/recommendations` | 获取个性化学习计划（LangGraph） |
| `POST` | `/chats/{id}/notes` | 生成 AI 学习笔记卡片 |
| `GET` | `/chats/{id}/notes` | 获取最新的 AI 笔记 |
| `GET` | `/chats/{id}/notes/pdf` | 将 AI 笔记下载为 PDF |
| `POST` | `/chats/{id}/quiz-remedial-notes` | 针对答错的题目生成补救笔记 |
| `GET` | `/chats/{id}/quiz-remedial-notes` | 获取最新的补救笔记 |
| `GET` | `/chats/{id}/quiz-remedial-notes/pdf` | 将补救笔记下载为 PDF |
| `POST` | `/chats/{id}/clear-knowledge` | 清空某个会话的全部向量 + 文档 |
| `GET` | `/health` | 健康检查（`{"status": "ok"}`） |

---

## 🗂 项目结构

```
RagVault/
├── frontend/               # React + Vite + TypeScript
│   ├── src/
│   │   ├── api/            # TanStack Query hooks
│   │   ├── components/     # UI 组件（shadcn/ui + 自定义）
│   │   ├── pages/          # 路由页面
│   │   ├── store/          # Zustand stores
│   │   ├── types/          # TypeScript 类型
│   │   └── theme.ts        # 设计系统 token
│   ├── nginx.conf          # 前端容器的生产环境 Nginx 配置
│   └── Dockerfile
├── backend/                # FastAPI 应用
│   ├── app/
│   │   ├── models/         # SQLAlchemy ORM（user, chat, document, message, quiz, note, memory）
│   │   ├── schemas/        # Pydantic schema
│   │   ├── routers/        # FastAPI 路由（auth, chats, documents, messages, quiz, notes）
│   │   ├── services/       # 业务逻辑（rag, quiz, notes, ingestion, recommendation, auth）
│   │   ├── utils/          # 解析器、分块器、FastEmbed 向量化、ChromaDB 客户端
│   │   └── core/           # 认证依赖、安全
│   ├── alembic/            # 数据库迁移
│   └── Dockerfile          # python:3.11-slim + Tesseract + ffmpeg
├── models/                 # 遗留的 GGUF 目录（docker-compose 已不再使用）
├── docker/
│   └── nginx.conf          # Nginx 反向代理配置（可选 profile）
├── docker-compose.yml      # 4 个服务（postgres, chromadb, backend, frontend）
└── .env.example            # 配置模板
```

---

## 🎮 远程 / 自托管 LLM（可选）

由于答案生成只是一次普通的 OpenAI 兼容 HTTP 调用，你可以把
RagVault 指向任何兼容服务器而非 DeepSeek —— 包括运行在另一台机器上的
本地 vLLM / llama.cpp / Ollama 网关：

```bash
LLM_PROVIDER=custom
LLM_BASE_URL=http://192.168.1.10:11434/v1
LLM_MODEL=qwen2.5:7b-instruct
LLM_API_KEY=not-needed-but-must-be-non-empty
```

即便对于无需密钥的本地服务器，`LLM_API_KEY` 也必须是非空字符串，
因为客户端拒绝发送未认证的请求。

---

## 📝 许可证

MIT License。详见 [LICENSE](LICENSE)。

本版本（`alpha-v1.3`）衍生自 Meet Paladiya 的原始
[RagVault](https://github.com/Meet-paladiya/RagVault) 项目。
上游提交历史被有意丢弃；本仓库从单个 `alpha-v1.1` 提交开始，
`alpha-v1.2` 增加了设置对话框，`alpha-v1.3` 增加了 Windows 桌面版
（Tauri v2 壳 + PyInstaller 后端，详见
[docs/desktop-packaging.md](docs/desktop-packaging.md)）。

---

> **致贡献者：** 答案生成统一集中在
> `backend/app/services/llm_client.py` —— 新增 AI 功能时请调用其中的
> `chat_completion()` / `stream_chat_completion()`，而不要直接导入某家服务商的
> SDK，这样服务商就能继续通过 `.env` 自由切换。
