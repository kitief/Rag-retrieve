# RagVault 桌面化封装方案

> 目标：把原来的「Docker Compose 四服务栈」变成一个**双击即用的桌面应用**——用户看到的是一个普通图标，双击后不需要 Docker、不需要命令行、不需要浏览器。
>
> 适用版本：alpha-v1.2（commit `3ae6034`）起草，alpha-v1.3 落地。

> **⚠️ 状态说明（alpha-v1.3 之后）**
> 本文是桌面化改造的**设计记录**，正文保留了当初「Docker 与桌面双轨并存」阶段的推演过程。
> 该决策**已被推翻**：Windows 桌面版成为**唯一交付形态**，Docker / Docker Compose / WSL
> 相关文件（`docker-compose.yml`、`backend/Dockerfile`、`frontend/Dockerfile`、
> `docker/nginx.conf`、`frontend/nginx.conf`、`backend/docker-entrypoint.sh`、`.dockerignore`）
> 以及 Postgres 专用的 Alembic 迁移链、`asyncpg`、`start.ps1` 均已从仓库删除。
> 阅读时请把下文所有「Docker 保留 / 不动 compose / 双轨并行」的表述视为**历史方案**，
> 以第 9 节和当前 README 为准。

---

## 0. 结论先行（TL;DR）

| 问题 | 结论 |
| --- | --- |
| 用什么壳？ | **Tauri v2**，不是 Electron |
| 后端怎么办？ | Python 打成 **sidecar 可执行文件**（PyInstaller onedir），由 Rust 主进程拉起并在退出时杀掉 |
| Postgres 怎么办？ | **换成 SQLite**。不需要 sidecar Postgres |
| Chroma 怎么办？ | **换成进程内 `PersistentClient`**。代码里已经写好了降级路径 |
| Redis 怎么办？ | 不需要。全仓 grep `redis` 零命中，本来就没有 |
| 安装包多大？ | **150–250 MB**（不是 5 MB——见第 6 节，这一节请务必读完） |
| 前端要改吗？ | 要改 3 处：API base、SSE 读流、文件下载 |
| 现有 Docker 部署要删吗？ | ~~不删~~ → **已删**。桌面版是唯一交付形态，Docker/Compose/WSL 相关文件已从仓库移除 |

一句话概括改造思路：

> **把「4 个容器」压成「1 个进程」。** 只要后端能在一个进程里同时提供 API + 前端静态文件 + 向量库 + 关系库，Tauri 就只是给它套一个窗口而已。

---

## 1. 为什么不能直接用 PakePlus「一键转桌面」

PakePlus / Pake 这类工具的本质是：**Tauri 壳 + 指向一个远程 URL**。它们回答的是「把已有网站变成桌面入口」，而不是「把本地服务栈装进用户电脑」。

对本项目，PakePlus 路线的硬伤：

- 前端 `frontend/src/api/client.ts:6` 的 `baseURL: '/api'` 需要一个**后端**来响应。PakePlus 壳里没有后端。
- 后端依赖 Postgres、Chroma 两个**独立服务**（`docker-compose.yml`）。壳里也没有。
- 退一步：把后端部署到公网，让壳指向它 —— 那你的产品就变成了 SaaS，用户必须联网、API Key 存在你服务器上、文档上传走公网。这和「本地知识库」的定位（隐私、离线）直接冲突。

**PakePlus 只适合一种场景**：你只想做一个「演示版 / 答辩用的客户端入口」，后端跑在你自己的服务器上。作为毕设演示的补充形态可以，作为交付形态不行。

所以真正的问题是：**如何把 Python 服务塞进桌面应用**。这正是 Tauri `externalBin`（sidecar）要解决的。

---

## 2. 现状盘点：改造前必须知道的事实

| 项 | 现状 | 桌面化影响 |
| --- | --- | --- |
| 服务数量 | 4 个容器：postgres / chromadb / backend / frontend-nginx | 必须压到 1 个进程 |
| 关系库 | `postgresql+asyncpg://...@postgres:5432` (`backend/app/config.py`) | 换 SQLite |
| 向量库 | `chromadb.HttpClient(host="chromadb")` (`backend/app/utils/chroma_client.py:28`) | 换 `PersistentClient` |
| Embedding | fastembed `BAAI/bge-small-en-v1.5`，从 HF 下载到 `/hf_cache` (`backend/app/utils/embedder.py:28`) | **必须预置进安装包**，否则首启要联网 |
| 前端托管 | nginx 容器，`/api` 反代到 `backend:8000` | 改由 FastAPI `StaticFiles` 托管 |
| 进程入口 | `docker-entrypoint.sh`：`alembic upgrade head` + `uvicorn --host 0.0.0.0 --port 8000` | 换成 `--host 127.0.0.1 --port <稳定端口>`（见下方「端口为什么不能随机」） |
| 跨域 | `main.py:106-114` 白名单只含 `localhost:3000/80`、`frontend` | 同源方案下不用改；`tauri://` 方案下必须加 |
| SSE 流式 | `frontend/src/api/messages.ts:66` 用 `fetch` + `body.getReader()` 手解析 | WebView2 没问题；WKWebView 要降级 |
| 文件下载 | `frontend/src/api/notes.ts:38-43` 用 `createObjectURL` + `<a download>` | **Tauri 里默认会被吞掉**，必须接管 |
| 上传上限 | `backend/app/routers/documents.py:28` `MAX_FILE_SIZE = 2GB` | 建议降到 500MB |
| 本地 LLM | 无。走云端 OpenAI 兼容 API (`backend/app/services/llm_client.py`) | 不用打包模型权重，省 2–4 GB |
| 体积 | backend 933K / frontend 730K / `models/` 空 | 代码很小，体积全在运行时与依赖 |

**两个好消息**——它们让工作量比想象中小：

1. `backend/app/utils/chroma_client.py:17-42` **已经写了降级逻辑**：HTTP 心跳失败即返回 `chromadb.PersistentClient(path=cfg.chroma_persist_dir)`。桌面模式只要让 HTTP 不可达，就是嵌入式向量库，一行配置的事。
2. `backend/tests/conftest.py` 已经用 `sqlite+aiosqlite:///:memory:` 跑测试。**说明 ORM 层已经在 SQLite 上跑通过**，`postgresql.UUID` 在 SQLite 方言下能编译。换库不是从零开始。

---

## 3. 四条路线对比

| | **A. Tauri + Python sidecar**（推荐） | B. Electron + sidecar | C. 纯 Tauri 全家桶（Rust 重写后端） | D. PakePlus 远程瘦客户端 |
| --- | --- | --- | --- | --- |
| 壳体积 | ~10 MB（用系统 WebView） | ~100 MB（捆 Chromium） | ~10 MB | ~10 MB |
| 后端复用 | **100%**，Python 代码一字不改 | 100% | **0%**，RAG/解析/LLM 全用 Rust 重写 | 100%（但在服务器上） |
| 需要 Postgres sidecar 吗 | 否（用 SQLite） | 否（用 SQLite） | 否 | 不需要本地库 |
| 总安装包 | **150–250 MB** | 250–350 MB | 60–100 MB | ~10 MB |
| 工期 | **5–7 天** | 5–7 天 | 3–4 个月 | **半天** |
| 离线可用 | ✅ | ✅ | ✅ | ❌ |
| 主要风险 | PyInstaller 打包 chromadb/onnxruntime | 同左 + 体积 | 重写等于重做毕设 | 产品形态改变 |

**选 A**。理由：

- B 的 sidecar 逻辑和 A 完全一样（一样要打 Python 包），只是额外背 100 MB Chromium —— 没有收益。
- C 的包最小，但要用 Rust 重写 PDF/PPTX 解析（PyMuPDF 无对标品）、LangGraph 编排、fastembed 推理。这是重做毕设，不是封装。
- D 已在第 1 节排除。

> 关于「electron-sidecars 把 Postgres/Redis 当原生二进制打包」：这个思路是对的，但**本项目不需要**。Redis 本来就没有；Postgres 的唯一刚性用途是两个（UUID 类型、一条 `ALTER TABLE ... IF NOT EXISTS`），都能在 1 小时内消掉。为了保留 Postgres 而多打 200 MB 便携二进制 + 学 initdb/pg_ctl 生命周期管理（崩溃恢复、端口冲突、权限、Windows 服务化），是明显的負收益。**能在进程内解决的，不要用子进程解决。**

---

## 4. 目标架构

```
┌──────────────────────────────────────────────────────────┐
│  RagVault.exe  (Tauri v2 主进程, Rust)                    │
│                                                          │
│  1. 解析数据目录  %APPDATA%\com.ragvault.desktop\data\   │
│  2. spawn sidecar: --port <记住的端口或 47823..>          │
│  3. 读 sidecar stdout，等 "RAGVAULT_READY port=54321"     │
│  4. 轮询 GET /health 直到 200                             │
│  5. WebviewWindow → http://127.0.0.1:54321/               │
│  6. RunEvent::ExitRequested → child.kill()（只杀一次）    │
└───────────────────────┬──────────────────────────────────┘
                        │ spawn / kill
┌───────────────────────▼──────────────────────────────────┐
│  ragvault-backend.exe  (PyInstaller onedir, 单进程)        │
│                                                          │
│  FastAPI (uvicorn, 127.0.0.1:稳定端口)                    │
│   ├─ /api/*          业务路由（现有 routers 原封不动）      │
│   ├─ /               StaticFiles → frontend/dist (SPA)   │
│   └─ /health         就绪探针                             │
│                                                          │
│  SQLite      %APPDATA%\com.ragvault.desktop\data\ragvault.db │
│  Chroma      %APPDATA%\com.ragvault.desktop\data\chroma\    │
│  上传临时区   %APPDATA%\com.ragvault.desktop\data\uploads\temp\ │
│  模型缓存     <安装目录>\resources\fastembed\  (只读预置)   │
└──────────────────────────────────────────────────────────┘
```

### 为什么窗口加载 `http://127.0.0.1:PORT` 而不是 `tauri://localhost`

这是本方案里最容易被做错的一个决策。两种做法：

- **做法 1**：Tauri 以 `tauri://localhost`（Windows 上是 `http://tauri.localhost`）加载打包好的 `frontend/dist`，前端把 `baseURL` 改成 `http://127.0.0.1:PORT/api`。
- **做法 2**：后端自己用 `StaticFiles` 托管 `frontend/dist`，Tauri 窗口直接指向 `http://127.0.0.1:PORT/`。

**选做法 2**，四个理由：

1. **同源**。前端 `client.ts:6` 的 `baseURL: '/api'`、`messages.ts:66` 的 `fetch('/api/chats/.../messages')` 全部零改动。
2. **CORS 消失**。`main.py:106-114` 的白名单不用动。
3. **SSE 走真实 HTTP 源**。自定义协议 scheme 下 WebView 的流式读行为在各平台不一致；`http://127.0.0.1` 是标准 http 源，行为和普通浏览器一致，`proxy_buffering off` 那套经验继续有效。
4. **可独立验证**。做完这一步，**不装 Tauri，直接用浏览器打开 `http://127.0.0.1:PORT/` 就是一个能用的应用**。Tauri 变成纯装饰层，出问题容易二分定位。

代价：`dist` 要从 Rust 的 `frontendDist` 挪到 Python 的安装资源里。用 `--collect-data` / 直接放进 PyInstaller `datas` 即可，成本很低。

> 如果走做法 1，注意 Tauri v2 对外部源窗口的 IPC 有额外限制，需要在 `capabilities` 里声明 `"remote": { "urls": ["http://127.0.0.1:*"] }`。

---

## 5. 关键技术决策（逐条）

### 5.1 关系库：Postgres → SQLite

必须改的四处：

| 位置 | 问题 | 改法 |
| --- | --- | --- |
| `backend/app/models/{user,chat,document,message,note,quiz,memory}.py:2` | 7 个 model 都 `from sqlalchemy.dialects.postgresql import UUID` | 换成 `from sqlalchemy import Uuid`（SQLAlchemy 2.0 的方言无关类型，`Uuid(as_uuid=True)`），或最省事的 `String(36)` |
| `backend/app/database.py:20` | `ALTER TABLE chats ADD COLUMN IF NOT EXISTS is_deleted ...` —— SQLite 不支持 `IF NOT EXISTS` | 直接删掉这行（`create_all` 已建全表，这是历史补丁），或包 `try/except OperationalError` |
| `backend/app/models/quiz.py:13` | `score = Column(Numeric)` —— SQLite 上 `Numeric` 是浮点近似，读回会有 Decimal 精度告警 | 改 `Column(Float)` |
| `backend/app/config.py` 的 `database_url` | 写死 `postgresql+asyncpg://` | 加大分支：`sqlite+aiosqlite:///{data_dir}/ragvault.db` |

配套：连上后立刻执行

```python
# SQLite 必需，否则长任务（PDF 解析）期间其它请求会 database is locked
await conn.execute(text("PRAGMA journal_mode=WAL"))
await conn.execute(text("PRAGMA busy_timeout=5000"))
await conn.execute(text("PRAGMA synchronous=NORMAL"))
```

> **关于 alembic**：`alembic/versions/001_initial_schema.py` 里用的是 `sa.UUID()`（SQLAlchemy 通用类型），反而比 ORM 更可移植。但**桌面端不上 alembic**：迁移脚本要作为资源打包、用户机器上 `upgrade head` 失败极难恢复。桌面版用 `create_all` + 自维护一个 `schema_version` 表，升级时跑手写迁移函数，更可控。**alpha-v1.3 起整条 Alembic 迁移链已随 Docker 一并删除。**
>
> **关于已有数据**：alpha 阶段没有真实用户数据，**不做 Postgres→SQLite 迁移**。如果答辩机上有数据，写个一次性导出脚本（`pg_dump --data-only` → 逐表 INSERT）即可，不要做通用迁移器。

### 5.2 向量库：Chroma HttpClient → PersistentClient

代码已经支持，只需加配置开关：

```python
# backend/app/config.py
chroma_mode: str = "server"   # "server" | "embedded"
```

`chroma_client.py:17` 的 `get_chroma_client()` 在 `chroma_mode == "embedded"` 时直接返回 `chromadb.PersistentClient(path=cfg.chroma_persist_dir)`，跳过心跳探测（省 1–2 秒启动时间）。

注意：
- `PersistentClient` 会在内部拉起 sqlite + hnswlib，**首次创建 collection 较慢**（秒级），可接受。
- **不要**用文件锁之外的多进程方案。桌面版必须是单实例，用 Tauri 的 `tauri-plugin-single-instance` 保证第二次双击只激活已有窗口，否则两个进程同时打开同一个 chroma 目录会损坏索引。

### 5.3 Embedding 模型：必须预置，不能首启下载

`backend/app/utils/embedder.py:16-28` 用 `TextEmbedding(model_name, cache_dir=cfg.hf_home)`，首次运行会联网从 HF Hub 拉 `BAAI/bge-small-en-v1.5`（约 130 MB）。

桌面应用不能这样：用户可能没网、HF 可能被墙、首启卡 3 分钟会被当成卡死。

做法：

1. 构建阶段（CI 或本地脚本）执行一次 `TextEmbedding("BAAI/bge-small-en-v1.5", cache_dir="./build/fastembed")`，把整个 cache 目录塞进 PyInstaller `datas` 或 Tauri `bundle.resources`。
2. 运行时把 `hf_home` 指向该只读资源目录，并设置：
   ```python
   os.environ["HF_HUB_OFFLINE"] = "1"
   os.environ["FASTEMBED_CACHE_PATH"] = str(resource_dir / "fastembed")
   ```
3. 启动时 `assert` 模型目录存在，缺失就弹窗提示「安装包损坏」而不是静默联网。

> 注意资源目录是**只读**的（macOS 的 `.app/Contents/Resources`、Windows 的安装目录）。如果 fastembed 尝试往 cache 目录写东西会失败——把所有「可写」的东西（`HF_HOME` 的 lock、临时文件）指到 `%APPDATA%`，只把模型权重留在资源目录。稳妥做法是首启时把模型**复制**到 `%APPDATA%\com.ragvault.desktop\data\models\`（130 MB 一次性拷贝，首次启动多 5 秒，换来读写一致）。

### 5.4 端口协商：让它自己报，不要自己猜

❌ 反模式：Rust 先 `bind("127.0.0.1:0")` 拿端口再关掉，把端口传给 Python —— 存在 TOCTOU 竞态，别的进程可能抢走。

✅ 正确做法：

1. Rust 传一个**跨启动稳定**的端口（见下方「端口为什么不能随机」），uvicorn 绑定它。
2. 后端在 uvicorn 启动完成后**向 stdout 打印一行**约定的就绪信号：
   ```
   RAGVAULT_READY port=54321
   ```
   （在 `main.py` 的 `lifespan` 里读 `server.servers[0].sockets[0].getsockname()[1]`，或用 uvicorn 的 `Server` 对象回调。）
3. Rust 用 `tauri-plugin-shell` 的 `CommandEvent::Stdout` 逐行读，正则匹配到就关掉 stdout 监听、打开窗口。
4. 兜底：同时轮询 `GET /health`，两条路径任一成功即可；30 秒超时报错。

**安全加固**（强烈建议）：本地 HTTP 服务对**机器上任何进程和任何网页**都是可见的。加一层握手：

- Rust 生成随机 token，通过环境变量 `RAGVAULT_LOCAL_TOKEN` 传给 sidecar；
- 后端中间件校验除 `/health` 外所有请求的 `X-RagVault-Token`；
- 前端怎么拿 token？—— 做法 2 有个天然优势：**后端在返回 `index.html` 时注入** `<meta name="ragvault-token" content="...">`，前端从 DOM 读。零 IPC、零额外接口。
- 这能防住「用户在浏览器里打开恶意页面，页面偷偷 POST 到 127.0.0.1:54321 删你的库」。

### 5.5 CORS

做法 2（同源）下**不用改**。但如果将来切回 `tauri://` 或加了内嵌 WebView，把这两个源加进 `backend/app/main.py:106-114` 的白名单：

```python
"http://tauri.localhost",   # Windows (WebView2)
"tauri://localhost",        # macOS / Linux (WKWebView / WebKitGTK)
```

### 5.6 SSE 流式：WebView2 能用，WKWebView 要降级

`frontend/src/api/messages.ts:66` 用原生 `fetch` + `response.body.getReader()` 手工解析 SSE 行。这个写法在**Chromium 内核（WebView2）上完全正常**——所以 **Windows 端可以零改动**。

WKWebView（macOS）有已知问题：`response.body` 可能为 `null`、`TextDecoder` 抛错、第一次 `read()` 直接返回 `{done: true}`。

如果只交付 Windows 版（毕设场景通常如此），**这条可以先不做**，但要在代码里留探测：

```ts
// 启动时一次性探测
async function canStreamFetch(): Promise<boolean> {
  try {
    const r = await fetch('/health')
    if (!r.body) return false
    const reader = r.body.getReader()
    const first = await reader.read()
    reader.cancel()
    return !first.done || first.value?.length > 0
  } catch { return false }
}
```

探测失败则降级到 `XMLHttpRequest` + `onprogress` 累积文本、按 `\n\n` 切分事件。这是纯前端改动，与桌面化本身解耦。

### 5.7 文件下载：必须接管，否则点击无反应

`frontend/src/api/notes.ts:38-43` 和 `83-88` 用 `URL.createObjectURL(blob)` + `<a download>` 触发下载。**在 Tauri 里这个动作默认会被静默吞掉**（WebView 的下载请求没人处理）。

两种改法：

- **改法 a（推荐，2 小时）**：Tauri 主进程注册下载处理器（`WebviewWindow::on_download` / `tauri-plugin-upload` 的衍生），弹原生保存对话框，写盘后用 `tauri-plugin-opener` 打开所在文件夹。
- **改法 b（1 小时）**：前端 `isTauri()` 分支里不用 `<a download>`，改成 `fetch` 拿 blob → `invoke('save_file', { name, bytes })` → Rust 侧 `dialog.save()` + `fs.write()`。

**同理检查上传**：`frontend/src/components/documents/DropZone.tsx:26,85` 的拖拽上传走标准 `FormData`，Tauri 里没问题；但拖拽到窗口时 WebView 会先拦截 `drop` 事件用于导航——需要在 Rust 侧 `on_web_resource_request` 或前端加 `e.preventDefault()` + `e.stopPropagation()`，否则拖文件会「跳转页面」。

### 5.8 sidecar 生命周期：Tauri 不会帮你杀进程

这是 Tauri sidecar 最经典的坑。**`app.shell().sidecar()` spawn 出来的子进程，主进程退出时不会自动终止**——Windows 上会留下一个占着端口的孤儿 `ragvault-backend.exe`，下次启动就撞端口。

正确写法：

```rust
use std::sync::Mutex;
use tauri_plugin_shell::process::CommandChild;

struct Sidecar(Mutex<Option<CommandChild>>);

fn main() {
  tauri::Builder::default()
    .plugin(tauri_plugin_shell::init())
    .manage(Sidecar(Mutex::new(None)))
    .setup(|app| { /* spawn 后把 child 存进 Sidecar */ Ok(()) })
    .build(tauri::generate_context!())
    .expect("error building app")
    .run(|app_handle, event| {
      if let tauri::RunEvent::ExitRequested { .. } = event {
        if let Some(child) = app_handle.state::<Sidecar>().0.lock().unwrap().take() {
          let _ = child.kill();   // take() 保证只杀一次
        }
      }
    });
}
```

三个细节：

1. **`Option::take()` 保证只杀一次**——`ExitRequested` 可能触发多次，重复 kill 会 panic 或误杀复用 pid 的进程。
2. 监听 `RunEvent::Exit` 之外还要覆盖**窗口关闭**（用户点 X，窗口关但进程还在）。`ExitRequested` 在最后一个窗口关闭时触发；如果配置了 `tauri-plugin-window-state` 之类的插件，要确认它没拦截退出。
3. 加**兜底清理**：后端启动时把自己的 pid 写到 `%APPDATA%\com.ragvault.desktop\data\backend.pid`；下次启动时如果 pid 文件存在且 `/health` 探活成功，说明是上次的孤儿，直接 `taskkill /PID` 清掉再启动。

### 5.9 二进制命名约定（必踩）

Tauri 的 `externalBin` 要求 sidecar 文件名带目标三元组后缀：

```
src-tauri/binaries/ragvault-backend-x86_64-pc-windows-msvc.exe
src-tauri/binaries/ragvault-backend-aarch64-apple-darwin
```

- 查询当前三元组：`rustc -Vv | grep host`（Rust ≥ 1.84 可用 `rustc --print host-tuple`）。
- `tauri.conf.json` 里写 `"externalBin": ["binaries/ragvault-backend"]`（**不带后缀**）。
- Rust 侧 `app.shell().sidecar("ragvault-backend")` 也**只传 basename**。
- JS 侧如果要用 `Command.sidecar`，需要在 `capabilities` 里声明：
  ```json
  { "identifier": "shell:allow-execute",
    "allow": [{ "name": "ragvault-backend", "sidecar": true, "args": true }] }
  ```
- 建议**只在 Rust 侧 spawn**（不开放给 JS），既省 capabilities 配置，也避免前端被 XSS 后能任意执行本地二进制。

### 5.10 数据目录与首启

| 用途 | Windows | macOS | 说明 |
| --- | --- | --- | --- |
| 关系库 + 向量库 + 上传 | `%APPDATA%\com.ragvault.desktop\data\` | `~/Library/Application Support/<identifier>/data/` | 可写 |
| 模型（若拷贝） | `%APPDATA%\com.ragvault.desktop\data\models\` | 同上 | 首启从 resources 拷贝 |
| 日志 | `%APPDATA%\com.ragvault.desktop\data\backend.log` | 同上 | 由 shell 重定向后端 stdout/stderr |
| 内置资源 | 安装目录 | `.app/Contents/Resources` | **只读** |

Rust 侧用 `app.path().app_data_dir()` 取路径，通过 `--data-dir` 参数传给 sidecar，**不要在 Python 里猜路径**（打包后的 `__file__` 不可靠）。

**首启引导**：`app_settings` 表存 `llm_api_key`（见 `backend/app/routers/settings.py`）。桌面版首启在检测到无 key 时，直接打开 settings 对话框。这是必要的一步——否则用户打开应用发现「什么都问不了」。

### 5.11 单实例锁

桌面应用必须单实例，否则两个进程抢 SQLite 写锁和 Chroma 目录。用 `tauri-plugin-single-instance`，第二次启动时把已有窗口 `set_focus()`。

同理，后端也应该有兜底：启动时尝试对 `data\.lock` 加独占文件锁，失败就打印 `RAGVAULT_ERROR already_running` 并退出。

---

## 6. 体积真相：5 MB 是「空壳」，本项目不是

原始设想里「Tauri 打包出的应用体积可小至 5 MB，比 Electron 小约 20 倍」——这句话**只在双方都是纯前端壳时成立**。一旦你把 Python 运行时、原生依赖、embedding 模型塞进去，比例就完全变了。

实测估算（Windows x64）：

| 组成 | 解压后 | 说明 |
| --- | --- | --- |
| Tauri 壳（Rust + 系统 WebView 调用） | 8–15 MB | 真正「小 20 倍」的部分 |
| Python 3.11 运行时（onedir） | 15–20 MB | 含 stdlib |
| fastapi + uvicorn + pydantic + sqlalchemy 等纯 Python 依赖 | 30–40 MB | |
| **onnxruntime**（fastembed 的推理后端） | 50–60 MB | 单个最大的依赖 |
| **chromadb + hnswlib + 其 sqlite 扩展** | 40–50 MB | |
| **PyMuPDF** | 25–35 MB | PDF 解析，无轻量替代 |
| numpy + Pillow + python-pptx | 30–40 MB | |
| **embedding 模型 `bge-small-en-v1.5`** | **~130 MB** | onnx fp32 |
| 前端 dist | 2–3 MB | three.js 是大头 |
| **解压后合计** | **~330–390 MB** | |
| **安装包（NSIS + LZMA2）** | **~150–220 MB** | 压缩率约 0.5 |

对比：

| 方案 | 安装包 |
| --- | --- |
| Electron 空壳 | 80–120 MB |
| **本项目 Tauri 版** | **150–220 MB** |
| 本项目 Electron 版（同 sidecar） | 250–330 MB |
| Docker 方案（用户需装 Docker Desktop） | 应用 ~1 GB + Docker Desktop ~1.5 GB |

**所以真实收益是「体积小 1.5–2 倍 + 不用装 Docker Desktop（省 1.5 GB）+ 启动快 3–5 倍 + 一个图标」，而不是「5 MB」。** 这个预期必须在方案里说清楚，否则做完会被质疑「说好的 5 MB 呢」。

**还能往下压的地方**（按性价比排序）：

1. 模型换 int8 量化：130 MB → 35 MB，安装包立减 ~45 MB。（唯一改动是 fastembed 的模型名换成 `bge-small-en-v1.5` 的 quantized 变体，检索质量下降通常 < 2%。**最推荐**。）
2. `--exclude-module` 砍掉 chromadb 的客户端侧依赖（`opentelemetry`、`grpcio`、`posthog`）——注意不要砍掉 `PersistentClient` 路径需要的东西，砍错了运行时才报错，比较费时。
3. numpy 用 `numpy` 而非 `numpy+MKL`，已经是最小。
4. 上 UPX 压缩 exe/dll：省 10–20%，但**杀软误报率显著上升**，不建议。

---

## 7. 分阶段里程碑

阶段划分的原则：**M0 结束时就必须能在浏览器里跑通完整功能**，Tauri 前置于此，保证出问题时能二分定位是「服务层」还是「壳层」。

### M0：单进程化（0.5–1 天）⭐ 最关键

不改任何业务逻辑，只让后端脱离 Docker 独立跑起来。

- [x] `backend/app/config.py` 加 `RAGVAULT_EMBEDDED=1` 开关，切换 `database_url` / `chroma_mode` / 各路径默认值到 `--data-dir`
- [x] 7 个 model 的 `postgresql.UUID` → `sqlalchemy.Uuid`
- [x] `database.py:20` 的 `ALTER TABLE` 处理掉；加 WAL / busy_timeout PRAGMA
- [x] `quiz.py:13` `Numeric` → `Float`
- [x] `main.py` 挂 SPA 静态资源到 `/`，SPA fallback 到 `index.html`（最终用 ASGI 中间件实现，见下方「M0 实施记录」）
- [x] `uvicorn --host 127.0.0.1 --port 0`，打印 `RAGVAULT_READY port=...`
- [x] 新增 `scripts/run_desktop.py`（开发用：不打包，直接跑）

**验收**：`python scripts/run_desktop.py` → 浏览器打开 `http://127.0.0.1:PORT/` → **注册、上传 PDF、提问、生成笔记、导出 PDF、做题全部可用**，且不依赖任何容器。

#### M0 实施记录（已完成，2026-10-26）

实际落地与原方案的三处偏离，都是踩坑后修正的，后续阶段不要退回原写法：

1. **SPA 托管不能用 `@app.get("/{full_path:path}")` catch-all 路由。**
   FastAPI 按注册顺序匹配，`GET /chats/{chat_id}` 这类真实 API 路由会先命中，于是深链 `/chats/abc` 返回 401 而不是前端页面。
   改为 `backend/app/core/spa.py` 里的 `SpaMiddleware`（裸 ASGI）：在 router 外层先判断「是不是 API 路径」，不是才去找静态文件 / 回退 `index.html`。
   判定规则：精确命中 `/health`、`/config`、`/docs`、`/redoc`、`/openapi.json`，或以 `/api`、`/docs/` 开头 → 透传给下层。

2. **本地 token 只挂在 `/api/*` 上，不能拦 SPA 深链。**
   桌面模式下 `DesktopLocalMiddleware` 用 `X-RagVault-Token` 校验 `auth`/`chats`/`quiz`/`notes`/`settings`/`config` 前缀的 `/api/` 请求；如果连静态资源和深链也校验，浏览器直接导航就会 401。
   同时该中间件负责把 `/api/xxx` 改写成 `/xxx`，补上 Docker 里 nginx `proxy_pass .../` 去掉前缀的行为 —— 这样前端 `baseURL: '/api'` 在两种部署下完全一致。
   前端侧由 `frontend/src/lib/desktop.ts` 从后端注入的 `<meta name="ragvault-token">` 读取 token，`client.ts` / `messages.ts` / `i18n/index.ts` 三处请求都要带上。

3. **`get_settings()` 是 `lru_cache`，engine 是模块级常量**，所以 `scripts/run_desktop.py` 必须在 `import app.main` **之前**把所有环境变量写好（`RAGVAULT_EMBEDDED`、`DATA_DIR`、`WEB_DIST_DIR`、`HF_HOME`、`RAGVAULT_ENV_FILE`）。
   `RAGVAULT_ENV_FILE` 默认 `.env`，桌面模式显式置空，避免继承仓库里指向 Postgres 的 Docker 配置。

另外两处计划外的必要修复：

- `utils/chunker.py` 的 `tiktoken.get_encoding("cl100k_base")` 会在导入时联网下载 BPE 表，离线环境会让后端启动失败 → 改为 try/except 降级到近似计数（CJK 1 字 1 token，其余 `(字符数+3)//4`）。
- `routers/documents.py` 后台解析任务自建 engine，SQLite 下必须单独挂 PRAGMA，否则并发上传报 `database is locked`；上传上限在桌面模式降到 500 MB（解析器仍是整篇读入内存）。

**实测结果**（宿主 venv，Python 3.11.9，端口 8793，`RAGVAULT_LOCAL_TOKEN=devsecret123`）：

| 检查项 | 结果 |
| --- | --- |
| `GET /` / 深链 `/chats/abc` `/quiz` `/login` | 200，token meta 已注入 |
| 静态资源 / `/docs` / `/openapi.json` | 200 |
| `/api/config` 无 token / 错 token | 401 `Invalid or missing local token.` |
| `/api/config` 带 token | 200 |
| 未匹配的 `/api/nope` | 404（不落到 SPA） |
| 注册 / 建会话 / 上传 PDF | 201 / 201 / 202，文档 `processed`，1 chunk |
| 流式提问 | 200，SSE 正常，citation `photosynthesis.pdf` p.1 |
| 生成笔记 / 导出 PDF | 201 / 200，`%PDF-`，21736 bytes |
| 生成测验 | 500（当时未配 API key，符合预期） |
| Playwright 全流程（注册→上传→提问→设置弹窗） | 通过，console 无报错 |

配好 LLM 之后再跑一遍完整验收（临时脚本 `_setup/accept_m0.py`，**已随 `_setup/` 临时目录一并删除**：本地起一个假的 OpenAI 兼容端点，把问答、出题、点评、标题全部承接，不需要真 key）：

| 步骤 | 结果 |
| --- | --- |
| 保存设置 | 200，`provider=custom` `model=mock-model` |
| 上传解析 | `processed`，1 chunk |
| 流式提问 | 200，76 字符，内容来自模型，citation 正确 |
| 生成笔记 / 导出 PDF | 201，1 张卡片 / 200，21297 bytes，`%PDF-` |
| 生成测验 | 201，20 题 |
| 交卷 | 200，18/20，score 90.0，2 道错题 |
| 错题笔记 / 导出 PDF | 201，2 张卡片 / 200，22256 bytes，`%PDF-` |
| 学习建议 | 200，含生成的 Markdown |

**结论：M0 验收通过。** `python scripts/run_desktop.py` 一个进程就能提供完整应用，不依赖 Docker、不依赖 Postgres/Chroma 服务端。

> 开发期注意：`spa.py` 曾把渲染后的 `index.html` 永久缓存，导致改完前端 `npm run build` 后页面还是旧 bundle。
> 现在缓存按 `(st_mtime_ns, st_size)` 失效，重建后刷新即可，不必重启后端。

顺带修掉一个前端渲染 bug：`AnimatePresence` 里的乐观消息气泡和 `StreamingBubble` 没有 `key`，状态清空后旧的 DOM 节点不会被卸载，导致同一个提问渲染两次。已给两处补上 `key`，并用「比较已持久化消息文本」代替原来的「比较消息条数」判断（后者在两次 invalidate 乱序时会误判）。

### M1：PyInstaller 打包（1–2 天）⭐ 风险最高

- [x] `backend/ragvault-backend.spec`：onedir（**没有**用 onefile，每次启动解压到 temp、慢且杀软误报高）
- [x] `--collect-all` 等价配置：`chromadb`、`onnxruntime`、`fastembed`、`tiktoken`、`tiktoken_ext`、`pymupdf`(fitz)、`tokenizers`、`huggingface_hub`，以及 PDF 分层解析用的 `rapidocr_onnxruntime`（含三个 ONNX 模型）、`cv2`、`shapely`、`pyclipper`
- [x] `datas` 包含：`frontend/dist` → `frontend/dist`、fastembed 模型 cache → `fastembed`（`alembic` 已随 Docker 移除，不再收集）
- [x] 手工验证：`dist/ragvault-backend/ragvault-backend.exe --data-dir ./tmp --port 0` → 打印 `RAGVAULT_READY port=…`

**产物**：`dist/ragvault-backend/`，**406 MB**（`_internal/` + `ragvault-backend.exe` 28 MB），构建约 5 分钟。
其中 OCR 栈占大头：`cv2/cv2.pyd` 71 MB、`rapidocr` 的三个 ONNX 模型 16 MB、
`onnxruntime` 37 MB、`shapely`/GEOS 约 6 MB。曾经剔除掉 `opencv_videoio_ffmpeg*.dll`（27 MB）、
`pymupdf/mupdf-devel`（5 MB）与 `cv2/data/haarcascade_*.xml`（9 MB）——三者都不在
PDF→图像→OCR 这条路径上（详见 spec 里的 `_DROP_BINARY_NAMES` 注释）。

#### 入口拆分

为了让「开发脚本」和「冻结入口」共用同一份启动逻辑：

| 文件 | 作用 |
| --- | --- |
| `backend/app/desktop_boot.py` | 全部启动逻辑：参数解析、环境变量、`_MEIPASS` 感知的 bundle 路径、`RAGVAULT_READY` 握手 |
| `backend/desktop_entry.py` | PyInstaller 入口，只做 `sys.path` 兜底 + 调 `desktop_boot.main()` |
| `scripts/run_desktop.py` | 开发期薄壳（34 行），同样调 `desktop_boot.main()` |
| `backend/desktop_diag.py` | 逐模块 import 的诊断入口，用于二分「打包成功但运行时秒崩」 |
| `scripts/prepare_embedded_models.py` | 把 FastEmbed 模型预置到 `build/desktop/fastembed`，供 spec 打包 |

打包前必须准备两样东西（spec 里有断言，缺了直接构建失败）：

```bash
cd frontend && npm run build            # → frontend/dist
./.venv-desktop/Scripts/python.exe scripts/prepare_embedded_models.py
```

#### 踩到的两个坑（都会导致「打包成功、运行即崩」）

**① onnxruntime 导入时段错误，stdout 一片空白（exit 139 / 0xC0000005）**

最隐蔽的一个。`--help` 正常、一旦真的启动就立刻段错误，Python 层来不及打印任何 traceback。用 `desktop_diag.py` 逐模块 `exec` 才定位到 `import onnxruntime` 这一步。

根因：PyInstaller 收集依赖时把某个包自带的**旧版** VC 运行时（`msvcp140.dll` / `vcruntime140*.dll`，版本 **14.31.31103.0**）复制进 `_internal/` 并置于 DLL 搜索首位，而 onnxruntime 1.31.0 链接的是更新版本（系统 `System32` 里是 **14.51.36247.0**）。清理 `_internal/` 下那 4 个 DLL 后立即恢复。

修法（spec 里在 `Analysis()` 之后、`PYZ()` 之前）：剔除 vendored 副本，改从 `System32` 补：

```python
_VC_RUNTIME = {"msvcp140.dll", "msvcp140_1.dll", "vcruntime140.dll", "vcruntime140_1.dll"}
_system32 = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
a.binaries = [e for e in a.binaries if Path(e[0]).name.lower() not in _VC_RUNTIME]
_present = {Path(e[0]).name.lower() for e in a.binaries}
for _name in sorted(_VC_RUNTIME - _present):
    _candidate = _system32 / _name
    if _candidate.is_file():
        a.binaries.append((_name, str(_candidate), "BINARY"))
```

构建日志会打印 `[spec] VC runtime DLLs bundled: [...]`，可用于确认生效。

**② `tiktoken` 报 `Unknown encoding cl100k_base`**

编码表定义在独立的 `tiktoken_ext` 命名空间包里，PyInstaller 的静态分析看不到，运行时就只剩 `Plugins found: []`。修法是除了 `tiktoken` 之外还得收集 `tiktoken_ext`：

```python
datas += collect_data_files("tiktoken") + collect_data_files("tiktoken_ext")
hiddenimports += collect_submodules("tiktoken") + collect_submodules("tiktoken_ext")
```

`utils/chunker.py` 有 try/except 降级（近似计数），所以这个漏掉不会崩，只是 chunk 边界会和 token 计数不一致——属于**静默劣化**，值得修。

#### 验收（临时脚本 `_setup/smoke_frozen.py`，已随 `_setup/` 删除）

脚本 spawn exe、从 stdout 读 `RAGVAULT_READY port=N`，然后走完整链路：

| 步骤 | 结果 |
| --- | --- |
| 握手 | `port=63424` |
| `/health` | 200 `{'status': 'ok', 'version': '1.2.0'}` |
| SPA 首页 / 深链 `/chats/does-not-exist` | 200 / 200（都是 `index.html`） |
| 注册 / 设置 / 建会话 / 上传 | 201 / 200 / 201 / 202 |
| 文档解析 | `processed`，1 chunk —— **embedding 用的是包内模型，全程离线** |
| 流式提问 | 200，76 字符，citation `[{'source': 'photosynthesis.pdf', 'page': 1}]` |
| 笔记 / PDF | 201，1 张卡片 / 200，21343 bytes，`%PDF-` |
| 测验 | 201，20 题 |
| 数据落盘 | `chroma`、`ragvault.db`、`uploads` 三个都在 `--data-dir` 下 |

**结论：M1 验收通过。** 冻结后的单文件目录树可以独立运行，不依赖系统 Python、不依赖 Docker、不联网下载模型。

> 测试脚本注意：桌面形态前端走 `/api/...` 前缀（`DesktopLocalMiddleware` 去前缀），直接打 `GET /chats/...` 会被 `SpaMiddleware` 当作深链返回 HTML。写验收脚本时 REST 调用一律加 `/api`。
>
> 残留进程会锁住 `chroma/chroma.sqlite3`，导致下次 `rmtree` 报 `WinError 32`。清理：`Get-Process ragvault-backend | Stop-Process -Force`。

### M2：Tauri 壳（1 天）

- [x] `src-tauri/` 初始化（`single-instance` 插件；**没有**用 `tauri-plugin-shell` 和 `opener`，见下方偏离说明）
- [x] 后端二进制随包分发（用 `bundle.resources`，而不是 `binaries/` + `externalBin`）
- [x] spawn + 端口握手 + `/health` 探活 + `WebviewWindowBuilder::new(app, "main", WebviewUrl::External(url))`
- [x] `RunEvent::Exit` 杀子进程 + **Job Object 兜底**（强杀也不漏）
- [x] 窗口配置：`min_inner_size(1100, 720)`、`inner_size(1280, 860)`

**验收结果：通过。** 启动后 4–6 秒出现应用界面（其中冻结后端自身启动约 3 秒），无控制台窗口，关窗后任务管理器里没有残留进程。

#### M2 实施记录（已完成，2026-10-26）

**文件**

| 文件 | 作用 |
| --- | --- |
| `src-tauri/Cargo.toml` | `tauri 2.12.5` + `tauri-plugin-single-instance 2` + `windows-sys 0.61`（只为 Job Object） |
| `src-tauri/tauri.conf.json` | `productName: RagVault`、`identifier: com.ragvault.desktop`、`app.windows: []`（窗口由 Rust 建，因为 URL 要等运行时端口）、`bundle.resources` 带上整棵 `dist/ragvault-backend` |
| `src-tauri/src/main.rs` | 全部逻辑：选数据目录 → 生成 token → spawn → 握手 → 建窗 → 退出清理 |
| `src-tauri/capabilities/default.json` | 只有 `core:default`；特权动作全在 Rust 侧，webview 不需要 shell 权限 |
| `src-tauri/icons/` | `make_icons.py` + Pillow 生成 `.ico` 与多尺寸 `.png` |

**三处与原方案的偏离，以及为什么**

1. **不用 `externalBin` / `tauri-plugin-shell`，改用 `bundle.resources` + `std::process::Command`。**
   `externalBin` 只接受**单个可执行文件**，而 PyInstaller 产物是「exe + `_internal/`」的 onedir 目录（406 MB），塞不进 sidecar 模型。用 `resources` 把整个目录带上，Rust 侧用标准库 spawn，顺带省掉 shell 插件的一整套权限声明。
   代价：需要自己解析 stdout 握手 —— 而这本来就是方案要求的。

2. **`RunEvent::Exit` 之外再加 Windows Job Object。**
   文档原方案靠 `Option::take()` + pid 文件兜底。实测 pid 文件方案有两个洞：进程被强杀时来不及写、pid 会被复用。Job Object 开 `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`，把子进程放进去后，**只要壳进程以任何方式消失（含 Task Manager 强杀、崩溃），内核立刻连带杀掉后端**。
   实测：`Stop-Process -Force` 强杀壳 → 1 秒内 `ragvault-backend.exe` 消失。没有 Job Object 时会永久残留并占着 SQLite 与端口。

3. **数据目录与 WebView2 profile 都给了环境变量逃生口**（`RAGVAULT_DATA_DIR`、`RAGVAULT_WEBVIEW_DIR`）。
   起因是开发机沙箱下 `%APPDATA%` 不可写，但这条路顺带解决了便携模式与自动化测试（Playwright 直接打 `http://127.0.0.1:<port>/` 就能驱动和 webview 里一模一样的应用）。

**踩到的三个坑（都很隐蔽）**

| 症状 | 根因 | 修法 |
| --- | --- | --- |
| 壳报 `The backend exited before reporting a port`，但同一个 exe 手动跑完全正常 | 读线程用 `BufReader::read_line(&mut String)`，子进程输出里的中文路径是 cp936 字节 → `Err` → `while let Ok(..)` **静默退出线程** → channel 断开，看起来和「进程退出了」一模一样 | 改 `read_until(b'\n', &mut raw)` 读字节 + `String::from_utf8_lossy`；`Err` 分支必须打日志再 break。配套在 `desktop_boot.py` 加 `_force_utf8_stdio()`，管道 stdio 强制 UTF-8 |
| 握手成功但报 `Could not create the app window: 拒绝访问 (os error 5)` | WebView2 要自己建 profile 目录，默认位置不可写 | `webview_dir()` + `.data_directory(profile)`；启动前 `create_dir_all` |
| 建窗失败后后端仍在跑 | `setup()` 里 `open_window` 失败只 `return Err`，`app.manage(state)` 还没执行，`Exit` 事件里 `try_state` 拿不到状态 | 建窗前先构造好 `BackendProcess`，失败分支显式 `shutdown(&state)` |

**验收明细**

| 检查项 | 结果 |
| --- | --- |
| 窗口出现 | 标题 `RagVault`，渲染登录页，深蓝渐变 / logo / 三条特性 / 右侧登录卡片全部正常 |
| 单实例 | 二次启动 → 进程数仍为 1 壳 1 后端，第二次的进程自行退出并把已有窗口 `set_focus()` |
| 优雅关窗（`CloseMainWindow`） | 1 秒内壳与后端双双消失，日志 `[shell] backend stopped` |
| 强杀壳（`Stop-Process -Force`） | 1 秒内后端被 Job Object 回收，无残留 |
| token 注入 | `GET /` 的 HTML 含 `<meta name="ragvault-token" content="…">`（32 字符） |
| token 校验 | `/api/config` 与 `/api/chats` 无 token → `401 {"detail":"Invalid or missing local token."}`；带 token → `200` |
| 全链路（走壳） | 注册 201 → 建会话 201 → 上传 202 → `processed (1 chunks)` → 流式提问 200 → 笔记 201（1 卡） |
| 窗口内真实 UI（Playwright 打壳的同源地址） | 注册落 `/chats` → 拖入 PDF 显示 `Ready / 1 chunks` → 提问得到回答且 **user 气泡只有 1 条** → 点用户行弹出菜单 → 开设置弹窗 → 服务商下拉与模型下拉都在 → console 零报错 |

**开发命令备忘**

```powershell
# 1) 准备前端与后端二进制
cd frontend; $env:TEMP="$PWD\.esbuild-tmp"; $env:TMP=$env:TEMP; npm run build
cd ..; .venv-desktop\Scripts\python.exe scripts\prepare_embedded_models.py --cache-dir .desktop-data\models
      .venv-desktop\Scripts\pyinstaller.exe backend\ragvault-backend.spec --noconfirm

# 2) 跑壳（debug）
$env:PATH = "C:\Users\<you>\rust-rustup\toolchains\stable-x86_64-pc-windows-msvc\bin;" + $env:PATH
cd src-tauri; cargo build; .\target\debug\ragvault-desktop.exe
```

`cargo build` 增量 5–30 秒；冷启动首次 `cargo fetch` 超过 10 分钟（tauri/wry/tao/windows 依赖树很大）。

### M3：桌面适配（1–2 天）

- [x] 首启引导：无 `llm_api_key` 时自动打开 settings
- [x] 文件下载接管（原生保存对话框）
- [x] 拖拽上传的 `preventDefault` 修复
- [x] 本地 token 校验中间件 + 注入到 `index.html`
- [x] 日志落盘 + 崩溃时保留 stderr（sidecar 的 stderr 要转发到日志文件，否则出问题完全不可诊断）
- [x] 上传上限 2 GB → 500 MB，改流式写盘

### M4：发布（1–2 天）

- [x] 图标（`.ico` / `.icns` / `.png` 多尺寸）
- [x] NSIS 安装包；WebView2 bootstrapper（`windows.webviewInstallMode` 默认 `downloadBootstrapper`，安装时自动补齐 Runtime）
- [x] 安装/卸载全链路验证（静默安装 → 运行 → 版本核对 → 静默卸载）
- [ ] 代码签名（Windows Authenticode）。**不签名会有杀软误报**，这是交付体验的硬伤，能签就签 —— *本阶段无证书，跳过；首次运行提示见下方说明*
- [ ] `tauri-plugin-updater` + GitHub Releases（可选）—— *明确不做（见第 9 节）*
- [ ] macOS：`codesign` + `notarytool` 公证（若要做 Mac 版，额外 1–2 天）—— *明确不做，只交付 Windows 版*

**总工期：5–8 天**（熟悉 PyInstaller 的前提下；不熟悉打包的话按 10 天估）。

#### M4 实施记录（2026-10-27）

**版本号（`1.2.0 → 1.3.0`）同步点** —— 桌面版的版本号散落在 5 个文件里，bump 时必须全部覆盖：

| 文件 | 字段 |
| --- | --- |
| `frontend/package.json` | 根 `version`（不要动依赖条目） |
| `frontend/package-lock.json` | 根 `version` **与** `packages[""].version` 两处 |
| `src-tauri/tauri.conf.json` | 根 `version`（决定安装包与 exe 的产品版本） |
| `src-tauri/Cargo.toml` | `[package].version` |
| `src-tauri/Cargo.lock` | `name = "ragvault-desktop"` 条目的 `version` |
| `backend/app/main.py` | `API_VERSION`（`/health`、`/config`、OpenAPI 的唯一来源） |

发布命令（PowerShell）：

```powershell
# 1) 前端
cd frontend; $env:TMPDIR="$PWD\.esbuild-tmp"; $env:TEMP="$env:TMPDIR"; $env:TMP="$env:TMPDIR"; npm run build
# 2) 同步 bundle 到 PyInstaller 产物（tauri 不重新打包 PyInstaller 产物！）
Copy-Item frontend/dist/* dist/ragvault-backend/_internal/frontend/dist/ -Recurse -Force
# 3) 发布构建（release profile 冷编译约 2–8 分钟 + NSIS 打包 + 复制 406 MB 资源）
$env:PATH = "C:\Users\<you>\rust-rustup\toolchains\stable-x86_64-pc-windows-msvc\bin;" + $env:PATH
$env:CARGO_HOME = "C:\Users\<you>\rust-cargo"
cd RagVault; frontend\node_modules\.bin\tauri build
# 产物：src-tauri\target\release\ragvault-desktop.exe 与 src-tauri\target\release\bundle\nsis\*.exe
```

踩坑（M4 新增）：

1. **`tauri build` 必须从 `RagVault/` 根目录跑**，不能在 `frontend/` 下跑 —— CLI 会把 CWD 及其子目录扫一遍找 `tauri.conf.json`，从 `frontend/` 找不到会直接 panic（`Couldn't recognize the current folder as a Tauri project`）。CLI 本身装在哪无所谓（`frontend/node_modules/.bin/tauri` 也行）。
2. **`tauri build` 不会重新打包 PyInstaller 后端**。`bundle.resources` 只是照搬 `dist/ragvault-backend/`，所以前端改完除了 `npm run build`，还要手动把 `frontend/dist` 拷进 `dist/ragvault-backend/_internal/frontend/dist`，否则安装包里是旧 bundle（vite 输出的旧 hash 文件会一直累积，注意先清掉）。
3. **release profile 是全新编译**，debug 的增量缓存帮不上忙：全部依赖重编一遍约 5–8 分钟（`opt-level = "s"` + `lto` + `codegen-units = 1` 比debug慢得多），属正常现象。
4. **NSIS 下载需要代理**。`tauri build` 首次打包会从 GitHub 拉 `nsis-3.13.zip` 和 `nsis_tauri_utils.dll`，国内直连必然 `failed to bundle project: timeout: global`。它读的是 `HTTPS_PROXY`/`HTTP_PROXY` 环境变量（不是 git 的 `http.proxy`），所以构建前要 `export https_proxy=http://127.0.0.1:7897`。已经下过一次后会缓存到 `%LOCALAPPDATA%\tauri\NSIS`，后续构建不再联网。
5. **NSIS 安装包在中文路径下静默安装会失败（退出码 2）**。从 `C:\Users\…\新毕设\…\RagVault_1.3.0_x64-setup.exe` 直接 `/S` 安装什么都不做；把同一个 exe 复制到 `C:\temp_rv\setup.exe` 再 `/S` 就正常装到 `%LOCALAPPDATA%\RagVault`（`ragvault-desktop.exe` + `backend\` + `uninstall.exe`）。**结论：交付时把安装包放在纯 ASCII 路径下再双击/静默安装**，并如实告知用户。
6. **PyInstaller 冻结后 `API_VERSION` 是编译进 PYZ 的**，改了 `backend/app/main.py` 必须重跑 PyInstaller，否则 `tauri build` 打出来的安装包里 `/health` 还是旧版本号（本阶段踩过：壳是 1.3.0、后端还是 1.2.0）。

Win10/11 上的静默安装与卸载命令（不需要交互）：

```powershell
# 装（务必先复制到 ASCII 路径）
Copy-Item .\RagVault_1.3.0_x64-setup.exe C:\temp_rv\setup.exe
Start-Process C:\temp_rv\setup.exe -ArgumentList '/S' -Wait
# 卸
Start-Process "$env:LOCALAPPDATA\RagVault\uninstall.exe" -ArgumentList '/S' -Wait
```

**M4 验收记录（2026-10-27）**

| 项 | 结果（2.1.0，2026-10-29） |
| --- | --- |
| release 壳编译 | `Finished release profile in 1m 53s`，`target/release/ragvault-desktop.exe`（7,697,920 B，ProductVersion 2.1.0） |
| NSIS 打包 | `RagVault_2.1.0_x64-setup.exe` **178,098,441 字节（169.85 MiB）** |
| 静默安装 | `/S` 从 ASCII 路径 → `%LOCALAPPDATA%\RagVault`（`ragvault-desktop.exe` + `backend\` + `uninstall.exe`，23.2 秒） |
| 安装后启动 | 后端 `RAGVAULT_READY port=61515`，`/health` → `{"status":"ok","version":"2.1.0"}` |
| 本地 token 闸门 | 无 `X-RagVault-Token` 调 `/api/auth/login` → **401**；从 `index.html` 的 `<meta name="ragvault-token">` 取到 32 位 token 后正常 |
| 安装后前端 bundle | `assets/index-C8W6iVuc.js`（与源码构建一致） |
| 安装后 OCR | 7 页扫描件 → `ocr_pages=5`、`mean_confidence=0.987`、`text_chars=6876`、8 个 chunk；`.md`/`.csv`/`.docx`/`.doc` 均 `processed` |
| 冻结产物自测 | `--port 8791` 起 exe 后同样跑通上述五项（不经安装步骤） |
| 静默卸载 | exit 0，`%LOCALAPPDATA%\RagVault` 完全移除 |
| 安装包体积 | 136.83 MiB → **169.85 MiB**（+33 MiB，主要是 cv2 71 MB 与 rapidocr 的 ONNX 模型 16 MB） |
| 安装后磁盘占用 | **413.0 MiB / 1939 个文件**（`cv2.pyd` 71 MB、`model_optimized.onnx` 63 MB、`libopenblas64__*.dll` 36 MB、`ragvault-backend.exe` 27 MB、`mupdfcpp64.dll` 20 MB） |
| 代码签名 | **未做**（无 Authenticode 证书）。首次运行 SmartScreen 会拦，解决方式见下 |

> 上表的「安装后 OCR」一项是这次打包最关键的验收点：PyInstaller 只会收集它看得见的
> import，`rapidocr_onnxruntime` 的 ONNX 模型、`cv2` 的 `cv2.pyd`、`shapely` 的 GEOS DLL
> 全靠 `collect_all` 显式带上。**源码树里这四样都装着，所以本地跑得通不能说明冻结包跑得通**，
> 必须在装好的 exe 上跑一遍扫描件。

> **未签名安装包的首次运行提示**：Windows 会弹「Windows 已保护你的电脑」。点「更多信息」→「仍要运行」即可；或对安装包右键 → 属性 → 勾选「解除锁定」。这段说明应写进发布说明，否则答辩现场容易被卡住。

---

## 8. 风险表

| 风险 | 概率 | 影响 | 缓解 |
| --- | --- | --- | --- |
| PyInstaller 打包 chromadb/onnxruntime 失败 | **高** | 阻塞 | M1 单独成阶段、预留 2 天；备选 Nuitka / 嵌入式 Python 分发 |
| 模型离线加载失败（路径只读、lock 文件） | 中 | 首启卡死 | 首启拷贝到 `%APPDATA%`；`assert` 存在性而非静默联网 |
| SQLite 写锁冲突（解析大 PDF 时前端报 500） | 中 | 体验差 | 开 WAL + busy_timeout；解析任务串行化 |
| sidecar 进程泄漏（关窗后残留） | 中 | 撞端口、下次启不来 | `Option::take()` 只杀一次 + pid 文件兜底清理 + 启动时探活清孤儿 |
| 端口被占用 / 被抢 | 低 | 起不来，或 origin 变化导致本地设置失效 | 先 `bind` 探测，被占则依次尝试 47823–47826，全占才退回 `--port 0`；读 stdout 握手，不做 bind-then-close |
| WebView2 未安装（Win10 1803 以下） | 中 | 白屏 | 安装包内置 ever-green bootstrapper |
| 杀软误报（未签名 exe） | 高 | 用户不敢装 | 代码签名；准备「如何加白名单」的说明文档 |
| 本地服务被恶意网页调用（localhost CSRF） | 中 | 数据泄露/删除 | 本地 token 校验 + `Origin` 检查 |
| WKWebView 的 SSE 读流不可用（macOS） | 中 | 回答不流式 | 只交付 Windows 版；或在 `messages.ts` 加三重探测降级 |
| 大文件上传占满内存 | 中 | OOM | 降上限到 500 MB + 流式落盘而非 `await file.read()` |
| 中文/空格路径导致 sidecar 找不到资源 | 中 | 启动失败 | 所有路径用 `Path` 拼接，传参不走 shell 字符串；构建时在中文路径下测一次 |

---

### 端口为什么不能随机

早期实现让 Rust 传 `--port 0`，由 uvicorn 向系统要一个空闲端口。这样启动最省事，但它有一个当时没意识到的副作用：**端口是 origin 的一部分**，而 WebView2 按 origin 分区 `localStorage`、IndexedDB 和 cookie。

于是 `http://127.0.0.1:56052/` 和 `http://127.0.0.1:62282/` 是两个完全独立的存储区。每次启动换端口，就等于给应用换了一个空的存储区——用户切到浅色模式、关掉应用、再打开，又变回深色；语言、登录态、引导标记、上次打开的会话也一并丢失。开发时看不出来，因为 Vite 固定在 `localhost:3000`，origin 一直没变。

现在的做法（`src-tauri/src/main.rs`）：

1. 上次成功的端口写在 `<data>/app-port.txt`，下次启动优先复用，origin 因此稳定。
2. 复用前先 `bind` 探测；被占用则依次尝试 `FALLBACK_PORTS = [47823, 47824, 47825, 47826]`。
3. 后端启动失败（探测与真正绑定之间被抢）会**换下一个候选重试**，而不是直接放弃。
4. 全部失败才退回 `--port 0`，此时功能正常，但本地设置会丢失——这是最后兜底，不是默认路径。

只有真正绑定成功的端口才会写回 `app-port.txt`。

另外 `frontend/public/theme-boot.js` 会在 bundle 加载前重放上次的主题，避免浅色用户每次启动先闪一下深色。

## 9. 明确不做的事（范围控制）

写清楚「不做什么」比「做什么」更能保证按期交付：

- ❌ **不打包本地 LLM**（GGUF）。`models/` 目录已被 `.gitignore` 忽略，说明这条路已经放弃过。云端 OpenAI 兼容 API 是当前架构，保持。
- ❌ **不做 Postgres → SQLite 的通用数据迁移器**。alpha 阶段无真实数据。需要就写一次性脚本。
- ✅ **Docker / Compose / WSL 已全部移除**。桌面版是唯一运行形态，仓库里不再保留任何容器相关文件、配置或文档；`asyncpg`、`alembic` 迁移链、`docker-entrypoint.sh`、两个 `Dockerfile`、两份 `nginx.conf`、`docker-compose.yml`、根目录 `start.ps1` 均已删除。
- ❌ **不做自动更新**（M4 列为可选）。毕设场景价值低、引入签名复杂度高。
- ❌ **不为 Electron 维护第二套壳**。选定 Tauri 后，Electron 方案只在文档里作为对比存在。
- ❌ **不保留第二条启动路径**。`scripts/dev.ps1` 与 `npm run tauri dev` 之外不再维护任何「多服务」启动脚本。

---

## 10. 参考资料

- Tauri v2 sidecar 官方文档（`externalBin`、目标三元组命名、capabilities）：<https://v2.tauri.app/develop/sidecar/>
- Tauri sidecar 生命周期（`RunEvent::ExitRequested` 杀子进程、`Option::take()`）：<https://github.com/stuffbucket/skills/blob/main/plugins/stuffbucket/skills/tauri-sidecar/SKILL.md>
- WKWebView `ReadableStream` 流式读的已知限制与降级：<http://m.php.cn/faq/2588054.html>
- Electron 原生二进制打包（`asarUnpack`、`app.asar.unpacked` 路径）：<https://yarnpkg.com/en/package/@nuwax-ai/file-server>
- 便携 Postgres 二进制体积参考（压缩 ~4 MB / 解压 ~20 MB，仅 postgres+initdb+pg_ctl）：<http://github.cc/twinfer/embedded-postgres-binaries>
