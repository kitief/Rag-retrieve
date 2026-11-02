# RagVault

> 自托管 · RAG 驱动的 AI 学习系统 · 云端 LLM + 本地向量化
>
> **版本 `alpha-v2.2`** · 仓库地址：<https://github.com/kitief/Rag-retrieve>
>
> 简体中文 | [English](README.en.md)

一个面向学生的自托管检索增强生成（RAG）学习平台。上传 PDF、PPTX/PPT、Word（DOCX/DOC）、Markdown、纯文本或 CSV 表格即可创建「知识空间」，随后可以进行提问、生成测验、创建 AI 学习笔记、追踪薄弱知识点，并获得个性化学习建议。

所有**答案生成**都通过 OpenAI 兼容接口交给云端 LLM 完成（默认使用 **DeepSeek**，也支持任何兼容端点）。**向量化则全程在本地完成**，由 FastEmbed ONNX 负责，因此你的文档只会在本机被转换成向量 —— 只有检索命中的片段会发送给模型服务商。

---

## ⚡ 快速开始

### 环境要求

| 工具 | 版本 | 说明 |
|------|---------|-------|
| 操作系统 | Windows 10 1809+ / Windows 11 | 需要 WebView2（Win11 自带，Win10 一般已随 Edge 安装） |
| 内存 | 最低 8GB | 后端进程 + WebView2 + 嵌入模型 |
| 磁盘 | 1.5GB 可用空间 | 安装包约 170 MiB，安装后约 413 MiB |
| LLM API Key | — | DeepSeek：https://platform.deepseek.com/api_keys |

### 1. 安装

下载并双击 `RagVault_2.2.0_x64-setup.exe`。安装位置为
`%LOCALAPPDATA%\RagVault`（无需管理员权限），用户数据在
`%APPDATA%\com.ragvault.desktop\data`。

> **首次运行**：安装包未做代码签名，Windows SmartScreen 会提示「已保护你的电脑」。
> 点「更多信息」→「仍要运行」；或对安装包右键 → 属性 → 勾选「解除锁定」再装。

### 2. 填入 API Key

首次启动会弹出引导窗口，把 DeepSeek（或任何 OpenAI 兼容端点）的 API Key 填进去即可。
之后随时可以在侧边栏底部的「设置」里修改。密钥只保存在本机的 SQLite 数据库里。

### 3. 开始使用

注册账号、创建知识空间、上传文档，然后就可以开始学习了！

> ⚠️ 运行时需要联网（用于调用 LLM 服务商接口）。向量化全程在本机完成，
> 只有检索命中的片段会发送给服务商。

从源码构建请见下方 [Windows 桌面版](#-windows-桌面版) 一节。

---

## 🖥 Windows 桌面版

RagVault 就是一个 **Windows 桌面应用**：双击图标启动，后端（PyInstaller 冻结的
FastAPI + SQLite + 嵌入式 Chroma）由 Tauri 壳自动拉起，界面在原生 WebView2 窗口里运行。
不需要 Docker、不需要 Python、不需要浏览器。

**安装包**：源码版本为 `2.2.0`，构建产物位于
`src-tauri/target/release/bundle/nsis/RagVault_2.2.0_x64-setup.exe`（约 170 MiB）。

> 已发布的安装包是 [alpha-v2.1](https://github.com/kitief/Rag-retrieve/releases/tag/alpha-v2.1)
> 里的 `RagVault_2.1.0_x64-setup.exe`（仓库私有，需登录 GitHub 才能下载）。
> `2.2.0` 的改动（学习计划弹窗、JWT 密钥按安装生成、主题与端口修复）目前**只在源码里**，
> 要拿到对应安装包需按下面的步骤自行构建；`alpha-v2.1` 装出来的版本不含这些改动。

**从源码构建**（需要 Rust MSVC 工具链 + Python 3.11 + Node 20+）：

```powershell
# 1) 前端（必须先做：spec 会把 frontend\dist 打进冻结产物）
cd frontend; npm run build
# 2) 冻结后端（约 5 分钟，产物约 406 MB）
.venv-desktop\Scripts\pyinstaller backend\ragvault-backend.spec
# 3) 打安装包（首次需联网下载 NSIS）
$env:https_proxy="http://127.0.0.1:7897"
frontend\node_modules\.bin\tauri build
```

> 第 2 步会把 `frontend/dist` 一起收进 `dist\ragvault-backend\_internal\frontend\dist`，
> 所以**前端要先生成**；改完前端只重跑第 2、3 步即可，不要再手工拷贝 dist。

完整的设计权衡、踩坑记录与验收清单见
[docs/desktop-packaging.md](docs/desktop-packaging.md)。

运行时形态：

| | 桌面版 |
| --- | --- |
| 数据库 | SQLite（WAL） |
| 向量库 | 嵌入式 Chroma（PersistentClient） |
| 启动 | 双击 exe |
| 数据位置 | `%APPDATA%\com.ragvault.desktop\data` |
| 安装位置 | `%LOCALAPPDATA%\RagVault` |
| 资源上传上限 | 500 MB |
| 访问方式 | 原生窗口（后端只监听回环端口） |

---

## 🏗 架构

```
Tauri v2 壳 (Rust)
   │  生成 RAGVAULT_LOCAL_TOKEN，拉起后端，解析 RAGVAULT_READY port=…
   ▼
WebView2 窗口 (React + Vite，由后端托管)
   │  REST + SSE  │
   ▼               ▼
FastAPI 后端 (单个 Python 进程，仅监听 127.0.0.1)
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
   ├── SQLite（%APPDATA%\com.ragvault.desktop\data\ragvault.db：用户、会话、消息、文档、测验、笔记）
   ├── 嵌入式 ChromaDB 0.5.18（%APPDATA%\com.ragvault.desktop\data\chroma，每个 chat_id 一个 collection）
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
> `scripts/setup_model.py` 和 `models/*.gguf` 也不再使用。

---

## 🌐 多语言（English / 简体中文）

用户能看到的一切 —— Web 界面、校验错误信息、以及模型写出的答案 —— 都可以在
**English** 和 **简体中文** 之间切换。

### 内置默认语言

在「设置 → Language」里勾选 `Use as deployment default`，或直接设置 `APP_LANGUAGE`
环境变量（`zh` / `en`，默认 `en`）。该值通过 `GET /config`（`default_language` 字段）
暴露给界面，因此全新安装首次打开应用时就会使用该语言。

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

## 🎨 主题（深色 / 浅色）

侧边栏底部有一个切换按钮，选择会存进 `localStorage`（`ragvault-theme-preference`），
下次打开仍是上次的样子。

### 为什么桌面版曾经会「复原」

主题确实存下来了，问题出在**存到了哪个 origin**：WebView2 按 origin 分区
`localStorage`，而桌面壳早期用 `--port 0` 让系统每次分配新端口，于是
`http://127.0.0.1:56052/` 和 `http://127.0.0.1:62282/` 是两个互不相干的存储区。
换个端口就等于换了个空存储区——主题、语言、登录态、引导标记全部重来。

现在端口是稳定的：上次成功的端口记在 `<data>/app-port.txt`，下次优先复用；
被占用时依次尝试 `47823–47826`，全占才退回随机端口。细节见
[`docs/desktop-packaging.md`](docs/desktop-packaging.md) 的「端口为什么不能随机」。

### 首帧不再闪一下深色

`frontend/public/theme-boot.js` 是一个在 `<head>` 里同步加载的普通脚本，
它会在 bundle 之前把上次的主题重放到 `<html>` 上。否则浅色用户每次启动都会先看到
深色默认值，等 React 水合后才跳成浅色。

---

## 📁 支持的文件类型

| 类型 | 扩展名 | 状态 | 处理方式 |
|------|-----------|--------|------------|
| PDF | `.pdf` | ✅ 已启用 | 分层流水线：先逐页审计，再只对坏页做 OCR（RapidOCR，模型随包分发）；表格转 Markdown |
| PowerPoint | `.pptx` `.ppt` | ✅ 已启用 | python-pptx 逐张幻灯片解析；二进制 `.ppt` 通过原始流提取作为回退 |
| Word（新版） | `.docx` | ✅ 已启用 | python-docx 按 body 顺序提取，表格压平为 `a \| b`；失败时回退 ZIP-XML |
| Word（旧版） | `.doc` | ✅ 已启用 | 纯 Python 实现 OLE2 + Word 片段表（`app/utils/doc_legacy.py`）；被改名的 RTF/HTML 也能读 |
| Markdown | `.md` `.markdown` | ✅ 已启用 | 直接读取，源码原样保留（标题、列表、代码块），切分为约 2000 字符的伪页面 |
| 纯文本 | `.txt` `.text` | ✅ 已启用 | 直接读取，UTF-8 / GB18030 / UTF-16 依次回退；按空行分段，无空行时按行分 |
| 表格文本 | `.csv` `.tsv` | ✅ 已启用 | 按整行分页，且**每页都重复表头**，保证检索到的片段仍能看懂列含义 |
| 图片 | `.png` `.jpg` `.jpeg` `.webp` `.bmp` `.tiff` | 🅿️ 已搁置 | Tesseract OCR + 对比度增强 —— 需 `ENABLE_OCR_UPLOADS=true` |
| 视频 | `.mp4` `.mkv` `.mov` `.avi` `.webm` | 🅿️ 已搁置 | ffmpeg 抽取音轨 → Faster-Whisper —— 需 `ENABLE_AUDIO_VIDEO_UPLOADS=true` |
| 音频 | `.mp3` `.wav` `.m4a` `.ogg` `.flac` `.aac` | 🅿️ 已搁置 | Faster-Whisper（PyAV 回退） —— 需 `ENABLE_AUDIO_VIDEO_UPLOADS=true` |

> ❌ 任何不在已启用列表中的类型都会被拒绝，并返回清晰的 422 错误信息。
> 📦 单文件最大上传体积：**500 MB**。

### 为什么 `.doc` 不需要额外依赖

`python-docx` 只认识 OOXML zip 容器，完全读不了 Word 97-2003。对本项目来说，
其余几条路都不划算：`olefile` 是又多一个要随包分发的依赖，COM 自动化要求目标
机器上装有正版 Word，`textract`/`antiword` 则要带原生二进制。因此
`backend/app/utils/doc_legacy.py` 用约 400 行纯 Python 直接实现了涉及的两种
小而稳定的格式：Compound File Binary 容器与 Word 片段表（piece table）。

损坏或后缀名不符的文件（RTF 或 HTML 被改成 `.doc`、纯文本顶着 Word 后缀）会
先被嗅探识别，再走对应回退路径，而不是让上传直接失败。

### PDF：先审计，再解析

绝大多数“上传了却答不出来”的 PDF 不是解析器坏了，而是**页面本身没有文字层**：
整页是一张扫描图，PyMuPDF 取到的文本是空串或几十个乱码字符。旧实现会把这类
页面静默丢弃，于是文档标着「已就绪」、实际只入库了几个碎片，模型只能回答
“在你的文档里找不到相关内容”。

`backend/app/utils/pdf_pipeline.py` 把这件事拆成两步：

1. **审计**（很快，不花 OCR 时间）。逐页测量文本量、图像覆盖率、乱码率、单字符
   行数，算出 0–1 的文本质量分，把页面分类为 `digital` / `scanned` / `hybrid` /
   `blank`，并标记 `needs_ocr`。判定“坏页”的关键是**图像盖满整页但文字量极少**
   —— 这正是隐藏着劣质 OCR 图层的扫描件。
2. **按需 OCR**。只对 `needs_ocr` 的页渲染成图再识别，且预处理是阶梯式的
   （原图 → 去斜 → 去噪二值化 → 组合），一旦置信度达标就停手 —— 因为对清晰
   页面做二值化反而会降低识别率。

被跳过的页会被**明确报出来**：文档行上存一份 `parse_audit`，界面在文档名旁显示
「OCR n 页」「m 页未被读取」徽章，点开可看到逐页的页码、类型、字符数、OCR
置信度与所用预处理。这样“为什么答不出来”是可查的，而不是靠猜。

两类失败也不会再被咽下去：扫描件在 OCR 被关掉、或机器上根本没有 OCR 引擎时，
上传会**直接失败并写明原因**（而不是入库 0 个片段后标成「已就绪」）；失败原因
存在文档行的 `error_message` 上，直接显示在列表里。

几个刻意的取舍：

- **不并行 OCR，但会限制线程数。** onnxruntime 默认按逻辑核开线程，负载高时
  互相抢核反而更慢：同一批页面实测库默认 12.4 秒/页，限到 8 线程 7.5 秒/页。
  多进程还能再快一点（6.1 秒/页），但打包后的程序要为此引入 `freeze_support()`
  与受控入口，收益不抵风险，所以长文档仍靠 `PDF_OCR_MAX_PAGES` 与
  `PDF_OCR_TIME_BUDGET_SECONDS` 封顶，线程数由 `PDF_OCR_THREADS` 控制。
- **有正常文字层的页面绝不 OCR。** 文字层是文字层，OCR 只会更差。
- **DPI 300 + 长边压到 1600 就够。** 实测 400 DPI 的字符数与置信度与 300 DPI
  无差别，只是白烧 CPU。

对一本 1400 页的扫描书，一次全量 OCR 是按小时计的（实测单页 4.5s，1439 页约
107 分钟）。默认 `PDF_OCR_MAX_PAGES=0`（不限），建议这类文档改成几百页，或先切
分上传。截断后审计里会写明「还有 m 页未被读取」，问题问到未读页时仍会老实回答
找不到，而不是编造。

### 重新启用已搁置的解析器

图片 OCR 与音视频转写**代码保留但入口被开关挡住**。PDF 的 OCR 已经默认开启，
下面只针对图片与音视频：

1. 在 `backend/requirements.txt` 中取消注释 `pytesseract` / `faster-whisper`
2. 安装系统组件：Tesseract-OCR（含 `chi_sim` 语言包）与 ffmpeg
3. 把 `.env` 里的 `ENABLE_OCR_UPLOADS` / `ENABLE_AUDIO_VIDEO_UPLOADS` 改成 true
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
| 向量数据库 | ChromaDB 0.5.18（嵌入式 `PersistentClient`） |
| 关系型数据库 | SQLite（WAL 模式） |
| 桌面壳 | Tauri v2（Rust）+ WebView2 |
| 打包 | PyInstaller（后端）+ NSIS（安装包） |
| 语音转文字 | *已搁置* —— Faster-Whisper 代码保留，默认禁用 |
| OCR | **RapidOCR**（PaddleOCR 的 ONNX 导出）—— 仅用于 PDF 扫描页，按需触发 |
| 认证 | JWT（access + refresh 双 token），bcrypt |

实现完全遵循上述技术栈，未作任何偏离。

---

## ⚙️ 配置

日常使用不需要碰任何配置文件 —— API Key、语言、模型都在应用内的「设置」对话框里，
保存在 `%APPDATA%\com.ragvault.desktop\data\ragvault.db`。下面这些环境变量只是内置默认值，
供开发时用 `.env` 覆盖（见 `.env.example`）：

| 变量 | 默认值 | 说明 |
|----------|---------|-------------|
| `LLM_PROVIDER` | `deepseek` | `deepseek` / `openai` / `custom` |
| `LLM_API_KEY` | *（空）* | 服务商 API 密钥 —— 留空时在应用内填写 |
| `LLM_MODEL` | `deepseek-chat` | 发送给服务商的模型标识 |
| `LLM_BASE_URL` | `https://api.deepseek.com/v1` | OpenAI 兼容的 base URL（覆盖预设值） |
| `LLM_TIMEOUT_SECONDS` | `180` | 单请求超时时间 |
| `LLM_MAX_RETRIES` | `3` | 遇到 429 / 5xx / 传输错误时的重试次数 |
| `APP_LANGUAGE` | `en` | 内置默认界面与 AI 语言（`en` / `zh`） |
| `ENABLE_AUDIO_VIDEO_UPLOADS` | `false` | 已搁置的音频/视频转写 |
| `ENABLE_OCR_UPLOADS` | `true` | PDF 扫描页的 OCR；同时也解锁已搁置的图片 OCR |
| `PDF_OCR_ENGINE` | `auto` | `auto` / `rapidocr` / `tesseract` —— `auto` 优先 RapidOCR |
| `PDF_OCR_DPI` | `300` | OCR 渲染分辨率；再高不会提升识别率，只更慢 |
| `PDF_OCR_MAX_SIDE` | `1600` | 渲染后图像长边上限，用于压住 CPU 开销 |
| `PDF_OCR_MAX_PAGES` | `0` | 单个文档最多 OCR 多少页（`0` = 不限）；长扫描书建议设小 |
| `PDF_OCR_TIME_BUDGET_SECONDS` | `1800` | 单个文档的 OCR 时间上限，超时即停并记录未读页 |
| `PDF_OCR_MIN_CONFIDENCE` | `0.75` | 低于此置信度的页记为低置信，并在界面提示复核 |
| `PDF_OCR_MAX_ATTEMPTS` | `3` | 预处理阶梯最多尝试几档（原图 → 去斜 → 二值化 → 组合） |
| `PDF_OCR_THREADS` | `8` | OCR 的 ONNX 线程数。实测库默认（每核一线程）12.4 秒/页，限到 8 线程 7.5 秒/页；填 `0` 交回库决定 |
| `PDF_MIN_TEXT_CHARS` | `200` | 文本量低于此值的整页图像判为“需要 OCR” |
| `PDF_EXTRACT_TABLES` | `true` | 把 PDF 表格转成 Markdown 一并入库 |
| `EMBEDDING_MODEL` | `BAAI/bge-small-en-v1.5` | FastEmbed ONNX 向量化模型 |
| `WHISPER_MODEL` | `base` | 仅在重新启用音频/视频时使用 |
| `CHUNK_SIZE` | `600` | 每个文本块的目标 token 数 |
| `CHUNK_OVERLAP` | `100` | 相邻文本块之间的 token 重叠 |
| `TOP_K` | `5` | 每次查询检索的文本块数量 |
| `WHISPER_DEVICE` | `cpu` | 有 GPU 时可设为 `cuda` |
| `DATA_DIR` | `%APPDATA%\com.ragvault.desktop\data` | 所有可变数据（数据库、向量、上传、模型缓存）的根目录 |
| `JWT_SECRET` | *（留空即自动生成）* | JWT 签名密钥。留空时首次启动为本次安装随机生成，写入 `<数据目录>/.jwt_secret`，之后每次启动复用同一把；只有需要强制共享密钥时才手填（≥32 字符） |

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
5. 在结果页点击 **生成学习计划**，会打开一个弹窗，基于你**最近 5 次测验**答错的知识点生成 Markdown 学习计划（含重点范围、复习策略、主动回忆技巧、下一步）。弹窗里可随时「重新生成」；计划是按需请求的，不打开弹窗就不会调用 LLM。

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

改代码之前，先从两种运行方式里挑一个——它们的启动成本差别很大：

| 方式 | 命令 | 适合 | 热重载 |
| --- | --- | --- | --- |
| **单进程 + Vite**（推荐） | `.\scripts\dev.cmd` | 日常改后端和前端 | 后端 + 前端都热重载 |
| 桌面壳 | `npm run tauri dev` | 验证原生另存为、首启引导等壳内行为 | 无（改前端要重新 build） |

### 首次准备

```powershell
# 后端依赖（一次性）
python -m venv .venv-desktop
.venv-desktop\Scripts\pip install -r backend\requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 前端依赖（一次性）
cd frontend
npm install --registry https://registry.npmmirror.com
```

### 日常开发：`scripts\dev.cmd`

```powershell
.\scripts\dev.cmd                 # API + Vite，两者都热重载
.\scripts\dev.cmd -BackendOnly    # 只跑 API（同时服务已构建的 SPA）
.\scripts\dev.cmd -NoReload       # 关掉热重载，调试断点时用
.\scripts\dev.cmd -Frozen         # 跑 PyInstaller 产物，和安装包里的二进制一致
.\scripts\dev.cmd -Stop           # 停掉所有相关进程
```

脚本会先把 API 拉到 `http://127.0.0.1:8000`（带 `--reload`，改 `backend/` 下任何文件自动重启），再起 Vite 到 `http://127.0.0.1:3000`，`/api` 通过 `vite.config.ts` 的代理转到后端。数据落在 `.desktop-data\`（SQLite + 嵌入式 Chroma），与安装版在 `%APPDATA%\com.ragvault.desktop\data` 的数据完全隔开。

> **为什么入口是 `.cmd` 而不是 `.ps1`**
>
> `dev.ps1` 没有数字签名。在默认的 `RemoteSigned` 策略下，本机自己写的脚本本来可以跑；
> 但如果 Authenticode 校验链路被安全软件或组策略限制，直接 `.\scripts\dev.ps1` 会报
> 「未对文件进行数字签名」或「AuthorizationManager check failed」。
>
> `dev.cmd` 不是 PowerShell 脚本，执行策略管不到它；它用
> `-ExecutionPolicy Bypass` 重新拉起 `dev.ps1`，且**只对那一个子进程生效**——
> 不改注册表、不改机器策略，子进程退出即失效。参数原样透传，所以两个文件的用法完全一致。
>
> 想永久放开（可选，需管理员）：`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`
> ——但本机若已受限，通常也不会生效，用 `dev.cmd` 更省事。

> 端口写死在 `vite.config.ts`（3000 和 8000），`-ApiPort` / `-WebPort` 只改后端监听、不改代理目标，脚本会给出警告。

### 验证桌面壳

```powershell
# 必须在仓库根目录执行：tauri CLI 只向下搜索 tauri.conf.json，
# 在 frontend\ 里跑会报 "Couldn't recognize the current folder as a Tauri project"
.\frontend\node_modules\.bin\tauri dev      # 首次编译 Rust 约 2 分钟，之后增量
```

壳会自己拉起后端并注入 `RAGVAULT_LOCAL_TOKEN`，所以那些只在桌面端出现的行为（原生另存为对话框、首启引导弹窗、拖拽上传）必须在这里测，浏览器里看不到。

改前端代码后 `tauri dev` 不会自动刷新——壳加载的是 `frontend\dist\` 的构建产物，要重新 `npm run build` 再重启壳。日常改 UI 用 `dev.ps1` 的 Vite 更快。

---

## ⚙️ 应用内设置

点击侧边栏底部的头像（或按 `Ctrl+,`）即可打开设置对话框。它包含两组设置：

| 分组 | 作用 |
| --- | --- |
| **Language（语言）** | 为当前浏览器在 English 和 中文之间切换界面、校验信息和 AI 答案。勾选 `Use as deployment default` 还会把该选择存为所有新访问者的默认值。 |
| **API** | 先选服务商（DeepSeek / OpenAI / 任何 OpenAI 兼容端点）并填好 base URL 与 API 密钥，再点「连接」。连接会用当前表单里的凭据探测 `GET /v1/models`，成功后模型字段才被解锁，并自动填入端点返回列表的第一个模型；未连接时模型字段为空且显示红色状态条，连接成功则转为绿色。密钥可以直接粘贴在输入框里，旁边的密钥菜单负责保存、切换、删除已存凭据。 |

**连接状态会持久化。** 探测结果（是否连通、模型列表、探测时的端点与密钥指纹）存在 `app_settings` 的 `llm_connection` 行里，所以关掉设置再打开，绿色徽章和模型列表还在，不必每次重新证明一遍。密钥本身不会被写进这一行，只存一个 `sk-…128e` 形式的掩码提示。

但绿色徽章不会一直亮着：只要 base URL、服务商或密钥与探测时不一致，接口就把这条记录标成 `stale`，前端按「未连接」处理并显示红色。改完配置却没有重新探测，界面不会假装还连着。侧边栏底部的「浅色模式」下方还有一个连接快捷按钮，绿色代表当前配置可用（并显示正在使用的模型名），红色代表没有可用连接，点一下直接跳到 API 面板。

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

这些值存放在 `app_settings` 表中，因此它们**能跨重启保留，并覆盖内置默认值**
—— 无需改任何文件。只有检索到的文档片段会发送给服务商；向量化始终留在本地。

对话框底部的 `Restore defaults` 会删除所有已存储的覆盖项，使内置默认值重新生效。

---

## 🧪 运行测试

测试套件不属于运行时产物，因此需要先安装额外依赖：

```bash
# 后端测试
cd backend
pip install -r requirements-dev.txt
pytest tests/ -v --tb=short

# 前端 lint
cd frontend
npm run lint
```

`backend/tests/conftest.py` 中的 fixture 使用内存 SQLite，不依赖任何外部服务。

当前规模：**141 个测试**（auth、解析器、PDF 分层流水线、摄取、进度、Chroma 守卫、连接状态持久化、JWT 密钥）。

> `conftest.py` 会固定 `JWT_SECRET` 为测试专用值。否则每跑一次测试，都会在仓库里按「首次启动」逻辑生成一个 `.jwt_secret` 文件（该文件在 `.gitignore` 里，但仍属污染）。

---

## 🔧 运行与排障

桌面版的日志由 Tauri 壳转发到启动它的控制台；日常开发时用 `scripts\dev.ps1` 直接看后端输出。

```powershell
.\scripts\dev.cmd -Stop     # 停掉所有相关进程（后端 + Vite）

# 数据目录（删掉即恢复出厂状态）
Remove-Item -Recurse "$env:APPDATA\com.ragvault.desktop"
```

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
├── frontend/               # React + Vite + TypeScript（构建产物被后端托管）
│   ├── public/
│   │   └── theme-boot.js   # 首帧主题重放（在 bundle 之前同步执行）
│   ├── src/
│   │   ├── api/            # TanStack Query hooks
│   │   ├── components/     # UI 组件（shadcn/ui + 自定义）
│   │   ├── pages/          # 路由页面
│   │   ├── store/          # Zustand stores
│   │   ├── types/          # TypeScript 类型
│   │   ├── lib/desktop.ts  # 本地 API token / 原生另存为
│   │   └── theme.ts        # 设计系统 token
│   └── vite.config.ts
├── backend/                # FastAPI 应用（单进程，同时托管 SPA）
│   ├── app/
│   │   ├── models/         # SQLAlchemy ORM（user, chat, document, message, quiz, note, memory）
│   │   ├── schemas/        # Pydantic schema
│   │   ├── routers/        # FastAPI 路由（auth, chats, documents, messages, quiz, notes）
│   │   ├── services/       # 业务逻辑（rag, quiz, notes, ingestion, recommendation, auth）
│   │   ├── utils/          # 解析器、分块器、FastEmbed 向量化、ChromaDB 客户端
│   │   ├── core/           # 认证依赖、安全、i18n、SPA 托管
│   │   ├── desktop_boot.py # 桌面启动：数据目录、端口、RAGVAULT_READY
│   │   └── main.py
│   ├── tests/              # pytest（内存 SQLite）
│   └── ragvault-backend.spec   # PyInstaller 打包配置
├── src-tauri/              # Tauri v2 壳（Rust）
│   ├── src/
│   ├── tauri.conf.json
│   └── Cargo.toml
├── scripts/
│   ├── dev.cmd             # 日常开发入口（绕过脚本执行策略）
│   ├── dev.ps1             # 实际启动逻辑：后端 + Vite
│   ├── run_desktop.py      # 单进程启动入口
│   └── prepare_embedded_models.py
├── docs/desktop-packaging.md
└── .env.example            # 仅开发用，安装版不读
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

本版本（`alpha-v2.2`）衍生自 Meet Paladiya 的原始
[RagVault](https://github.com/Meet-paladiya/RagVault) 项目。
上游提交历史被有意丢弃；本仓库从单个 `alpha-v1.1` 提交开始，
`alpha-v1.2` 增加了设置对话框，`alpha-v2.2` 增加了 Windows 桌面版
（Tauri v2 壳 + PyInstaller 后端，详见
[docs/desktop-packaging.md](docs/desktop-packaging.md)）。

---

> **致贡献者：** 答案生成统一集中在
> `backend/app/services/llm_client.py` —— 新增 AI 功能时请调用其中的
> `chat_completion()` / `stream_chat_completion()`，而不要直接导入某家服务商的
> SDK，这样服务商就能继续通过 `.env` 自由切换。
