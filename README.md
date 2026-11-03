# RagVault

> 把课件、讲义、教材变成能对话的私人助教
>
> **版本 `alpha-v2.2`** · 仓库地址：<https://github.com/kitief/Rag-retrieve>
>
> 简体中文 | [English](README.en.md)

RagVault 是一个装在 Windows 上的学习工具。你把 PDF 课件、PPT 讲义、Word 作业、Markdown 笔记之类的资料扔进去，它就变成你专属的助教：可以对着资料提问、自动出题考你、把整本书压成复习卡片、还会盯着你做错的题给你排学习计划。

所有回答都由云端大模型（默认 DeepSeek）生成，而**文档的向量化全程在你自己电脑上完成** —— 文档不会被上传，只有真正被检索到的那几段文字会发给模型服务商。

---

## 📑 目录

- [它能帮你做什么](#-它能帮你做什么)
- [5 分钟上手](#-5-分钟上手)
- [第一个知识空间](#-第一个知识空间)
- [四种核心玩法](#-四种核心玩法)（提问 / 出题 / 笔记 / 学习计划）
- [界面速查](#-界面速查)
- [上传资料](#-上传资料)
- [设置](#-设置)
- [常见问题](#-常见问题)
- [从源码运行与打包](#-从源码运行--自己打包)
- [技术说明](#-技术说明)

---

## 🎯 它能帮你做什么

| 你想干的事 | RagVault 怎么做 | 在哪儿点 |
| --- | --- | --- |
| 考前快速搞懂一章 | 对着课件提问，答案带出处（文件名 + 页码），不用通读 | 知识空间里的提问框 |
| 看看自己到底会不会 | 从你的资料里自动出 20 道选择题，当场判分并列出薄弱点 | 右侧「测验」面板 |
| 把一整本教材压成复习卡 | 逐页生成结构化笔记，可导出成可搜索的 PDF | 顶部「AI 笔记」 |
| 知道下一步该复习什么 | 根据最近 5 次测验的错题，生成一份 Markdown 学习计划 | 测验结果页「生成学习计划」 |
| 把某一门课的零散资料归拢 | 每门课开一个「知识空间」，资料、问答、测验、笔记互不干扰 | 侧边栏「新建对话」 |
| 换个模型 / 换个服务商 | 内置 DeepSeek、OpenAI，也支持任何 OpenAI 兼容端点 | 设置 → API |

一句话概括：**它不是「聊天框 + 上传按钮」，而是把「读 → 练 → 补」这条复习闭环做进了一个窗口。**

---

## 🚀 5 分钟上手

### 装

1. 从 [Releases](https://github.com/kitief/Rag-retrieve/releases/tag/alpha-v2.2) 下载 `RagVault_2.2.0_x64-setup.exe`（仓库是私有的，需要登录 GitHub）。
2. 双击安装。装到 `%LOCALAPPDATA%\RagVault`，**不需要管理员权限**。
3. 安装包没有代码签名，Windows 会弹「已保护你的电脑」——点「更多信息」→「仍要运行」。也可以先对安装包右键 → 属性 → 勾选「解除锁定」。

装完双击桌面图标即可，不需要装 Python、不需要 Docker、不需要开浏览器。

### 填一个 API Key

第一次打开时，设置窗口会自己弹出来并停在 **API** 面板（因为这时还没有可用的模型）。三步：

1. **服务商**：默认 `DeepSeek`，也可以换成 `OpenAI` 或任何 OpenAI 兼容端点。
2. **接口地址**：选预设时会自动填好，一般不用动。
3. **API Key**：去 [platform.deepseek.com/api_keys](https://platform.deepseek.com/api_keys) 拿一个，粘进输入框。

然后点 **连接**：

- 没连上 → 出现**红色**提示条，模型字段锁着，写着「请先连接以获取模型列表」。
- 连上了 → 变成**绿色**，模型字段解锁，并自动填上这个端点返回的第一个模型。

最后点 **保存**。密钥存在本机数据库里，不会上传；下次打开还是绿色的，不用重新连。

> 没有 DeepSeek 账号也能用：把服务商换成 `OpenAI`，或者选一个自定义端点填任意 OpenAI 兼容的地址和密钥。

### 注册并进去

- 第一次用点「注册」，填邮箱、昵称、密码即可。账号只存在本机数据库里，不联网验证。
- 登录后会**直接回到你上次待的知识空间**；如果还没有任何空间，会自动帮你建一个并跳进去。
  想再开一门课，点侧边栏的 **＋ 新建对话**。

> 登录页那句「支持 PDF 与 PPTX」是早期的文案，实际支持的格式见 [上传资料](#-上传资料)。

---

## 🗂 第一个知识空间

「知识空间」＝ 一门课 ＝ 一个独立的资料夹。每门课的资料、对话、测验、笔记都放在各自的格子里，不会互相串。

随便点一个空间进去，左边是**资料面板**，中间是**对话区**，右边是**测验/错题面板**。第一次看到中间写着「上传文档后即可提问。」—— 把课件拖进左下角的虚线框（或点一下选文件），等它从「解析中」变成「已就绪」就可以开始问了。

几条实用习惯：

- **一门课一个空间**，别把高数和近代史混在一起，检索会串味。
- 文件名起得具体一点（`第3章_傅里叶变换.pdf` 比 `课件.pdf` 好），因为答案的出处显示的就是文件名。
- 同一个空间可以陆续加资料，新文档会自动并入已有知识库；要彻底重来就点「清空知识库」。

---

## 🎓 四种核心玩法

### ① 对着资料提问

在中间的输入框里打字，**Enter 发送**，**Shift + Enter 换行**。

答案是一边想一边显示出来的（流式），并且**每条答案都带出处**：正文里会写 `[Source: 第3章_傅里叶变换.pdf, Page: 12]`，答案下方还有一个 `2 个来源` 的按钮，点开就是 `文件名 · p.12` 这样的标签。

如果资料里确实没有相关内容，它会直接说「在你的文档里找不到足够的信息」，而不是编一个答案 —— 这是刻意的设计，宁可说不知道。

> 有文档还在「解析中」时输入框会被禁用，下方提示「文档仍在解析中，解析完成后即可开始对话。」

### ② 自动出题考你

右侧 **测验** 面板里有两个入口：

| 入口 | 出什么题 | 按钮 |
| --- | --- | --- |
| **自动测验（全部文档）** | 覆盖这个空间所有文档的综合题 | 生成自动测验 |
| **主题测验** | 只针对你填的主题或章节，比如「神经网络」 | 生成主题测验 |

两种都是 **20 道单选题**（题量固定，不可调）。答完点 **提交测验**，立刻看到：

- 得分（`答对 18/20 题`）
- 每道错题的你的答案、正确答案、段落解析
- **需要复习：** 后面跟着薄弱知识点标签

所有历史测验都汇总在侧边栏的 **测验记录** 里，按知识空间分组，每条显示得分圆环（≥80% 绿、≥50% 主色、更低为红）和当时错的知识点。想知道「这门课我到底学得怎么样」，看这一页比看单次分数有用。

### ③ 把整本书压成复习卡片

点顶部中间的 **AI 笔记**，再点 **生成整篇文档笔记**。它会逐页读完所有资料，生成一组卡片：核心概念、定义、公式、要点。

卡片可以：

- 用搜索框过滤（「搜索笔记卡片…」）
- 单张复制到剪贴板
- 一键 **下载学习 PDF** —— 导出的是**可搜索**的 PDF，不是图片

适合考前一周：笔记先过一遍，再用测验自查。

### ④ 错题变成学习计划

每次测验结束后，结果页有三个按钮：**生成错题笔记与 PDF**、**再测一次**、**生成学习计划**。

- **生成错题笔记与 PDF**：只针对这次答错的题生成专项复习卡片，也能导出 PDF。右侧「测验错题笔记」面板里随时能翻。
- **生成学习计划**：弹出一份 Markdown 计划，包含重点范围、复习策略、主动回忆技巧、下一步该干什么。它读的是你**最近 5 次测验**的错题，所以测得越多，计划越贴近你的真实短板。

计划是**按需生成**的 —— 不点这个按钮就不会调用模型；弹窗里还可以随时「重新生成」。

---

## 🧭 界面速查

```
┌──────────────┬──────────────────────────────┬───────────────┐
│ 侧边栏       │ 中间：对话 / AI 笔记         │ 右侧面板      │
│              │                              │               │
│ 搜索对话…    │ [对话]  [AI 笔记]            │ [测验] [错题] │
│ ＋ 新建对话  │                              │               │
│ · 高数       │   你的问题                   │ 开始测验      │
│ · 近代史     │   ─────────────              │ 自动 / 主题   │
│              │   答案（带出处）             │               │
│              │                              │ 历史得分      │
│ 测验记录     │   ┌──────────────────┐       │               │
│ AI 已连接    │   │ 就你的文档提问…  │       │               │
│ 浅色模式     │   └──────────────────┘       │               │
│ 设置         │                              │               │
└──────────────┴──────────────────────────────┴───────────────┘
```

| 位置 | 是什么 |
| --- | --- |
| 侧边栏顶部搜索框 | 按名字过滤知识空间 |
| **＋ 新建对话** | 开一个新的知识空间 |
| 知识空间列表 | 单击进入；悬停可重命名 / 删除（删除会连资料、笔记、测验、向量一起清掉） |
| **测验记录** | 所有空间的历次测验与得分 |
| **AI 已连接 · 模型名** | 绿色＝模型可用，红色＝未连接。点一下直接跳到 API 设置 |
| **浅色模式 / 深色模式** | 切换主题，**会记住**，下次打开还是这个 |
| **设置** | 语言 + API（快捷键 `Ctrl + ,`） |
| 中间顶部 `[对话] [AI 笔记]` | 左边聊天，右边复习卡片 |
| 中间右上 `文档 (n)` | 折叠/展开左侧资料面板 |
| 右侧 `[测验] [测验错题笔记]` | 出题，以及查看错题复习卡 |
| 资料面板底部 **清空知识库** | 删掉这个空间的全部资料与向量，保留空间本身 |

---

## 📁 上传资料

| 类型 | 扩展名 | 说明 |
| --- | --- | --- |
| PDF | `.pdf` | **扫描版也能读**：先逐页判断有没有文字层，只对扫描页做 OCR；表格会转成 Markdown |
| PowerPoint | `.pptx` `.ppt` | 逐张幻灯片提取；老版 `.ppt` 也能读 |
| Word（新版） | `.docx` | 按正文顺序提取，表格压平成 `a \| b` |
| Word（旧版） | `.doc` | 原生支持，**不需要装 Word，也不需要额外依赖** |
| Markdown | `.md` `.markdown` | 原样保留标题、列表、代码块 |
| 纯文本 | `.txt` `.text` | 自动识别 UTF-8 / GB18030 / UTF-16 编码 |
| 表格文本 | `.csv` `.tsv` | 按行分页，**每页都重复表头**，切碎了也看得懂列含义 |

单文件最大 **500 MB**。不在表里的格式会被拒绝，并给出明确提示。

上传后文档有三种状态：**解析中**（带进度条和百分比）→ **已就绪** → 可以提问了；失败则显示 **解析失败** 和具体原因。

### 为什么扫描版 PDF 也能答

这是最容易踩的坑：很多 PDF 是整页扫描图，里面根本没有文字，普通解析器读出来是空的。以前遇到这种文件，界面会显示「已就绪」但实际一个字都没入库，于是提问只能得到「找不到相关内容」。

现在分两步：先**审计**每一页（有文字层？整页是图？空白？），再**只对真正需要的页**做 OCR。识别用的 RapidOCR 模型随安装包一起分发，**离线可用，不需要额外装任何软件**。

读完会在文档名旁显示徽章：

- `OCR 5 页` —— 有 5 页是靠 OCR 读出来的
- `3 页未读` —— 有 3 页没读到（比如超出页数上限）
- `2 页低置信` —— 有 2 页识别把握不大

点徽章打开 **解析报告**，能看到每一页是怎么读的、文本来自哪里、OCR 置信度多少。**干净的数字版 PDF 不会显示任何徽章** —— 没徽章就代表一切正常。

> 一本 1400 页的扫描书全量 OCR 大约要 100 分钟。默认不限页数，但建议这类大书分批上传，或先只传要复习的章节。
>
> 如果扫描件既没开 OCR、机器上又没有 OCR 引擎，上传会**直接失败并写明原因**，而不是假装成功。

---

## ⚙️ 设置

点侧边栏底部 **设置**（或按 `Ctrl + ,`），只有两个面板：

**语言** —— 在 English 和中文之间切换。切换会立即生效，并且同时作用于界面文字、校验提示和 AI 生成的答案。勾选「设为部署默认」还会把选择存为所有新用户的默认值。

**API** —— 前面「填一个 API Key」那节已经讲完了。补充两点：

- 输入框旁边的 **密钥** 菜单是个小保险箱：可以存多组密钥、随时切换当前生效的那组、删除不要的。密钥在界面上永远以 `sk-…128e` 这种掩码显示，不会明文回显。
- 改完接口地址或密钥后，绿色连接状态会失效变红 —— 因为它只代表「上次探测时那套配置是通的」。重新点 **连接** 才会变绿，界面不会假装还连着。

**连接状态会保存。** 关掉设置再打开，绿色徽章和模型列表都还在。侧边栏那个连接快捷按钮读的也是同一份状态。

---

## ❓ 常见问题

**问：提问一直说「找不到足够的信息」？**
先看文档名旁有没有 `N 页未读` 徽章。有的话打开解析报告，多半是扫描件没读到 —— 重新上传、或把页数上限调大。也可以试试把问题问得更贴近原文用词。

**问：上传后一直卡在「解析中」？**
大文件（尤其是几百页的扫描 PDF）确实要等。进度条会显示当前阶段（逐页审计 / 正在 OCR / 向量化…）。超过预期时间的话看文档是否变成「解析失败」，那里会写原因。

**问：换个模型要在哪儿改？**
设置 → API → 模型下拉框。列表是点 **连接** 时从端点实时拉的，也可以切到「手动输入模型名」自己填。

**问：数据存在哪儿？卸载会丢吗？**
安装在 `%LOCALAPPDATA%\RagVault`，你的资料和数据库在 `%APPDATA%\com.ragvault.desktop\data`。卸载不会自动删数据；想彻底清空就手工删掉后者（删掉即恢复出厂状态）。

**问：需要联网吗？**
生成答案、出题、写笔记、排学习计划需要联网（调云端模型）；**解析文档、向量化、检索全部在本机完成**。只有检索命中的片段会发给模型服务商。

**问：会不会把我的整份文档传上去？**
不会。发出去的是「这次检索命中的几段文字」加上你的问题。

---

## 🛠 从源码运行 / 自己打包

只想用的话，上面几节就够了。以下是给改代码的人的。

### 环境

| 需求 | 版本 |
| --- | --- |
| 操作系统 | Windows 10 1809+ / Windows 11（需要 WebView2） |
| 内存 | 8 GB 起 |
| 磁盘 | 1.5 GB 空闲（安装包 171 MiB，安装后约 419 MiB） |
| 工具链 | Python 3.11、Node 20+、Rust MSVC（打包才需要） |

### 首次准备

```powershell
python -m venv .venv-desktop
.venv-desktop\Scripts\pip install -r backend\requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

cd frontend
npm install --registry https://registry.npmmirror.com
```

想改内置默认值（模型、分块大小、OCR 参数等）时，把 `.env.example` 复制成 `.env` 再改。

> 国内下载 Python 包很慢的话，`pip` 的 `-i` 和 npm 的 `--registry` 都指向了镜像站，一般够用。

### 日常开发

```powershell
.\scripts\dev.cmd                 # API + Vite，两者都热重载
.\scripts\dev.cmd -BackendOnly    # 只跑 API（同时托管已构建的 SPA）
.\scripts\dev.cmd -NoReload       # 关掉热重载，方便断点
.\scripts\dev.cmd -Frozen         # 跑 PyInstaller 产物，和安装包里的二进制一致
.\scripts\dev.cmd -Stop           # 停掉所有相关进程
```

API 在 `http://127.0.0.1:8000`，Vite 在 `http://127.0.0.1:3000`，数据落在 `.desktop-data\`（与安装版的数据完全隔离）。

> **为什么入口是 `.cmd` 而不是 `.ps1`**：`dev.ps1` 没有数字签名，某些机器的 Authenticode 校验被安全软件限制时，直接跑会报「未对文件进行数字签名」或「AuthorizationManager check failed」。`dev.cmd` 不是 PowerShell 脚本，执行策略管不到它，它用 `-ExecutionPolicy Bypass` 拉起 `dev.ps1` 且只对那个子进程生效 —— 不改注册表、不改机器策略。参数原样透传，用法完全一致。

需要验证桌面壳特有行为（原生另存为、首启引导、拖拽上传）时：

```powershell
# 必须在仓库根目录：tauri CLI 只向下搜索 tauri.conf.json
.\frontend\node_modules\.bin\tauri dev
```

改前端后 `tauri dev` 不会自动刷新（壳加载的是 `frontend\dist\` 的构建产物），要重新 `npm run build` 再重启壳。日常改 UI 用 `dev.cmd` 更快。

### 打安装包

```powershell
# 1) 前端（必须先做：spec 会把 frontend\dist 打进冻结产物）
cd frontend; npm run build

# 2) 冻结后端（约 5 分钟，产物约 410 MB）
.venv-desktop\Scripts\pyinstaller backend\ragvault-backend.spec

# 3) 打安装包（首次需联网下载 NSIS）
$env:https_proxy="http://127.0.0.1:7897"
frontend\node_modules\.bin\tauri build
```

第 2 步会把 `frontend/dist` 收进 `dist\ragvault-backend\_internal\frontend\dist`，所以**前端必须先生成**；改完前端只重跑第 2、3 步，不要手工拷贝 dist。产物在 `src-tauri/target/release/bundle/nsis/`。

### 跑测试

```powershell
cd backend
pip install -r requirements-dev.txt
pytest tests/ -q

cd ..\frontend
npm run lint
```

`backend/tests/conftest.py` 用内存 SQLite，不依赖任何外部服务。当前规模：**141 个测试**（认证、各格式解析器、PDF 分层流水线、摄取进度、Chroma 守卫、连接状态持久化、JWT 密钥）。

> `conftest.py` 会固定 `JWT_SECRET`。否则每跑一次测试都会在仓库里生成一个 `.jwt_secret`。

---

## 🧱 技术说明

### 运行时形态

| | 桌面版 |
| --- | --- |
| 启动 | 双击 exe（Tauri v2 壳自动拉起后端） |
| 后端 | 单个 Python 进程，只监听 `127.0.0.1` 的固定端口 |
| 数据库 | SQLite（WAL） |
| 向量库 | 嵌入式 ChromaDB（PersistentClient，每个知识空间一个 collection） |
| 界面 | 原生 WebView2 窗口，由后端托管 SPA |
| 数据位置 | `%APPDATA%\com.ragvault.desktop\data` |
| 安装位置 | `%LOCALAPPDATA%\RagVault` |
| 上传上限 | 500 MB |

端口是**跨启动固定**的（上次成功的端口记在 `<data>/app-port.txt`，被占用就依次试 `47823–47826`）。这不只是洁癖：WebView2 按 origin 分区 `localStorage`，端口一变，主题、语言、登录态就全部回到出厂状态。

### 架构

```
Tauri v2 壳 (Rust)
   │  生成 RAGVAULT_LOCAL_TOKEN，拉起后端，解析 RAGVAULT_READY port=…
   ▼
WebView2 窗口 (React + Vite，由后端托管)
   │  REST + SSE  │
   ▼               ▼
FastAPI 后端 (单个 Python 进程，仅监听 127.0.0.1)
   ├── 认证 (JWT)
   ├── 摄取服务   解析 → 分块 → 向量化 → ChromaDB
   ├── RAG 服务   (LangGraph) 提问 → 检索 → LLM → 答案 + 引用（SSE）
   ├── 测验服务   并行分批出题 → 评分 → 薄弱知识点
   ├── 笔记服务   逐页生成卡片 → 可下载 PDF
   └── 推荐服务   (LangGraph) 错题 → 个性化 Markdown 学习计划
```

### 技术栈

| 层级 | 技术 |
| --- | --- |
| 前端 | React 18 + Vite + TypeScript + Tailwind CSS + shadcn/ui |
| 动画 / 3D | Framer Motion + Three.js |
| 状态管理 | TanStack Query v5 + Zustand v5 |
| 后端 | FastAPI + LangGraph |
| LLM | 云端 API，OpenAI 兼容 Chat Completions（默认 DeepSeek） |
| 向量化 | FastEmbed（ONNX Runtime）`BAAI/bge-small-en-v1.5` |
| 向量数据库 | ChromaDB 0.5.18（嵌入式） |
| 关系型数据库 | SQLite（WAL） |
| 桌面壳 | Tauri v2（Rust）+ WebView2 |
| 打包 | PyInstaller（后端）+ NSIS（安装包） |
| OCR | RapidOCR（PaddleOCR 的 ONNX 导出），仅用于 PDF 扫描页 |
| 认证 | JWT（access + refresh 双 token），bcrypt |

### 设计取舍

几个有意为之的选择，写在这里避免以后被当成 bug 改掉：

- **有正常文字层的页面绝不 OCR。** 文字层是精确的，OCR 只会更差。
- **不并行 OCR，但限制线程数。** onnxruntime 默认按逻辑核开线程，负载高时互相抢核更慢：实测库默认 12.4 秒/页，限到 8 线程 7.5 秒/页。所以线程数由 `PDF_OCR_THREADS` 控制（默认 8），长文档靠 `PDF_OCR_MAX_PAGES` 与 `PDF_OCR_TIME_BUDGET_SECONDS` 封顶。
- **OCR 用 300 DPI、长边压到 1600。** 实测 400 DPI 的字符数与置信度和 300 DPI 没有差别，只是白烧 CPU。
- **CSV 每页重复表头。** 从表格中段切出来的片段如果丢了表头，裸数字对检索毫无意义。
- **`.doc` 自己实现，不引依赖。** `python-docx` 读不了 Word 97-2003；`olefile` 要多带一个包，COM 要求装正版 Word，`textract`/`antiword` 带原生二进制。所以 `backend/app/utils/doc_legacy.py` 用纯 Python 实现了 CFB 容器与片段表。
- **文档不做自动补救式并行。** 怕 CPU 争抢把本该快的活拖慢，宁可让用户看到真实进度。

### 环境变量

日常使用不需要碰任何配置文件 —— API Key、语言、模型都在应用内设置里，存在本机 SQLite。下面这些只是内置默认值，供开发时用 `.env` 覆盖（见 `.env.example`）：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `LLM_PROVIDER` | `deepseek` | `deepseek` / `openai` / `custom` |
| `LLM_API_KEY` | *(空)* | 留空时在应用内填写 |
| `LLM_MODEL` | `deepseek-chat` | 发送给服务商的模型标识 |
| `LLM_BASE_URL` | `https://api.deepseek.com/v1` | OpenAI 兼容 base URL |
| `LLM_TIMEOUT_SECONDS` | `180` | 单请求超时 |
| `LLM_MAX_RETRIES` | `3` | 429 / 5xx / 传输错误的重试次数 |
| `APP_LANGUAGE` | `en` | 内置默认界面与 AI 语言（`en` / `zh`） |
| `ENABLE_OCR_UPLOADS` | `true` | PDF 扫描页 OCR；同时解锁已搁置的图片 OCR |
| `PDF_OCR_ENGINE` | `auto` | `auto` / `rapidocr` / `tesseract` |
| `PDF_OCR_DPI` | `300` | OCR 渲染分辨率 |
| `PDF_OCR_MAX_SIDE` | `1600` | 渲染后长边上限 |
| `PDF_OCR_MAX_PAGES` | `0` | 单文档最多 OCR 页数（`0` = 不限） |
| `PDF_OCR_TIME_BUDGET_SECONDS` | `1800` | 单文档 OCR 时间上限 |
| `PDF_OCR_MIN_CONFIDENCE` | `0.75` | 低于此置信度记为低置信页 |
| `PDF_OCR_MAX_ATTEMPTS` | `3` | 预处理阶梯最多尝试几档 |
| `PDF_OCR_THREADS` | `8` | OCR 的 ONNX 线程数（`0` = 交回库决定） |
| `PDF_MIN_TEXT_CHARS` | `200` | 文本量低于此值的整页图像判为需要 OCR |
| `PDF_EXTRACT_TABLES` | `true` | PDF 表格转 Markdown 一并入库 |
| `EMBEDDING_MODEL` | `BAAI/bge-small-en-v1.5` | FastEmbed ONNX 向量化模型 |
| `CHUNK_SIZE` | `600` | 每个文本块的目标 token 数 |
| `CHUNK_OVERLAP` | `100` | 相邻文本块的重叠 token 数 |
| `TOP_K` | `5` | 每次查询检索的文本块数量 |
| `DATA_DIR` | `%APPDATA%\com.ragvault.desktop\data` | 所有可变数据的根目录 |
| `JWT_SECRET` | *(留空即自动生成)* | 留空时首次启动为本次安装随机生成并写入 `<数据目录>/.jwt_secret`，之后复用；只有需要强制共享时才手填（≥32 字符） |

### 换成别的模型服务商

答案生成只是一次普通的 OpenAI 兼容 HTTP 调用，所以可以指向任何兼容服务器 —— 包括另一台机器上的 vLLM / llama.cpp / Ollama 网关：

```bash
LLM_PROVIDER=custom
LLM_BASE_URL=http://192.168.1.10:11434/v1
LLM_MODEL=qwen2.5:7b-instruct
LLM_API_KEY=not-needed-but-must-be-non-empty
```

即便本地服务器不需要密钥，`LLM_API_KEY` 也必须是非空字符串 —— 客户端拒绝发送未认证的请求。

### API 参考

启动后 API 文档在 `http://localhost:8000/docs`（Swagger UI）和 `/redoc`。

<details>
<summary>核心接口一览（点击展开）</summary>

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/auth/register` | 注册（字段：`email` / `name` / `password`） |
| `POST` | `/auth/login` | 登录，获取 JWT |
| `GET` / `POST` | `/chats` | 列出 / 创建知识空间 |
| `GET` / `PATCH` / `DELETE` | `/chats/{id}` | 读取 / 重命名 / 删除知识空间 |
| `POST` | `/chats/{id}/documents` | 上传并摄取文档（异步，返回 202） |
| `GET` | `/chats/{id}/documents` | 列出文档及处理状态 |
| `DELETE` | `/chats/{id}/documents/{doc_id}` | 删除单个文档及其向量 |
| `POST` / `GET` / `DELETE` | `/chats/{id}/messages` | 提问（SSE）/ 历史 / 清空 |
| `POST` | `/chats/{id}/quiz` | 生成测验 |
| `GET` | `/chats/{id}/quiz-history` | 该空间的历史测验 |
| `POST` | `/quiz/{id}/submit` | 提交答案，得分 + 薄弱点 |
| `GET` | `/chats/{id}/recommendations` | 个性化学习计划（LangGraph） |
| `POST` / `GET` | `/chats/{id}/notes` | 生成 / 获取 AI 笔记 |
| `GET` | `/chats/{id}/notes/pdf` | 笔记导出 PDF |
| `POST` / `GET` | `/chats/{id}/quiz-remedial-notes` | 错题笔记 |
| `GET` | `/chats/{id}/quiz-remedial-notes/pdf` | 错题笔记导出 PDF |
| `POST` | `/chats/{id}/clear-knowledge` | 清空该空间的资料与向量 |
| `GET` | `/health` | 健康检查 |

</details>

### 项目结构

```
RagVault/
├── frontend/               # React + Vite + TypeScript（构建产物被后端托管）
│   ├── public/theme-boot.js    # 首帧主题重放（在 bundle 之前同步执行）
│   └── src/
│       ├── api/                # TanStack Query hooks
│       ├── components/         # UI（shadcn/ui + 自定义）
│       ├── pages/              # 路由页面
│       ├── store/              # Zustand stores
│       └── theme.ts            # 设计系统 token
├── backend/                # FastAPI 应用（单进程，同时托管 SPA）
│   ├── app/
│   │   ├── models/             # SQLAlchemy ORM
│   │   ├── routers/            # FastAPI 路由
│   │   ├── services/           # rag / quiz / notes / ingestion / recommendation
│   │   ├── utils/              # 解析器、分块、FastEmbed、Chroma
│   │   │   ├── pdf_pipeline.py # PDF 分层解析（审计 + 按需 OCR）
│   │   │   └── doc_legacy.py   # Word 97-2003 纯 Python 解析
│   │   ├── core/               # 认证、安全、i18n、SPA 托管
│   │   └── desktop_boot.py     # 桌面启动：数据目录、端口、RAGVAULT_READY
│   ├── tests/                  # pytest（内存 SQLite）
│   └── ragvault-backend.spec   # PyInstaller 配置
├── src-tauri/              # Tauri v2 壳（Rust）
├── scripts/                # dev.cmd / dev.ps1 / run_desktop.py
└── docs/desktop-packaging.md   # 打包设计权衡与验收记录
```

### 排障

```powershell
.\scripts\dev.cmd -Stop     # 停掉所有相关进程

# 恢复出厂状态（连同资料、账号一起清空）
Remove-Item -Recurse "$env:APPDATA\com.ragvault.desktop"
```

桌面版的日志由 Tauri 壳转发到启动它的控制台；开发时直接看 `dev.cmd` 的输出。

---

## 📝 许可证

MIT License，详见 [LICENSE](LICENSE)。

本版本（`alpha-v2.2`）衍生自 Meet Paladiya 的原始
[RagVault](https://github.com/Meet-paladiya/RagVault) 项目。上游提交历史被有意丢弃；
本仓库从单个 `alpha-v1.1` 提交开始，`alpha-v1.2` 增加了设置对话框，
`alpha-v2.2` 增加了 Windows 桌面版（Tauri v2 壳 + PyInstaller 后端，详见
[docs/desktop-packaging.md](docs/desktop-packaging.md)）。
