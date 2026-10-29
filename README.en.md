# RagVault

> Self-Hosted · RAG-Powered AI Learning System · Cloud LLM + Local Embeddings
>
> **Release `alpha-v1.3`** · Repository: <https://github.com/kitief/Rag-retrieve>
>
> [简体中文](README.md) | English

A self-hosted Retrieval-Augmented Generation (RAG) learning platform for students. Upload PDF and PPTX files to create "knowledge spaces," then ask questions, generate quizzes, create AI study notes, track weak topics, and get personalized study recommendations.

All **answer generation** is delegated to a cloud LLM over an OpenAI-compatible API (**DeepSeek** by default, any compatible endpoint supported). **Embeddings stay local** via FastEmbed ONNX, so your documents are only ever reduced to embeddings on your own machine — only the retrieved snippets are sent to the model provider.

---

## ⚡ Quick Start

### Prerequisites

| Tool | Version | Notes |
|------|---------|-------|
| OS | Windows 10 1809+ / Windows 11 | Needs WebView2 (built into Win11; usually present on Win10 via Edge) |
| RAM | 8GB minimum | Backend process + WebView2 + embedding model |
| Disk | 1.5GB free | ~170 MiB installer, ~610 MB installed |
| LLM API key | — | DeepSeek: https://platform.deepseek.com/api_keys |

### 1. Install

Download and double-click `RagVault_2.1.0_x64-setup.exe`. Installs per-user to
`%LOCALAPPDATA%\RagVault` (no admin rights); user data lives in
`%APPDATA%\com.ragvault.desktop\data`.

> **First run**: the installer is not code-signed, so SmartScreen will warn. Click "More info" →
> "Run anyway", or right-click the installer → Properties → check "Unblock" before installing.

### 2. Enter an API Key

The first launch shows a setup dialog — paste a DeepSeek (or any OpenAI-compatible) API key.
You can change it later from the Settings dialog at the bottom of the sidebar. The key is stored
only in the local SQLite database.

### 3. Start Using It

Register an account, create a Knowledge Space, upload documents, and start learning!

> ⚠️ Internet is required at runtime for LLM inference (the provider API). Embeddings are computed
> locally, so only the retrieved snippets are sent to the provider.

To build from source, see [Windows Desktop Build](#-windows-desktop-build) below.

---

## 🖥 Windows Desktop Build

RagVault **is** a Windows desktop app: double-click the icon and the Tauri shell launches a
PyInstaller-frozen FastAPI backend (SQLite + embedded Chroma) behind a native WebView2 window.
No Docker, no Python install, no browser.

**Installer**: `src-tauri/target/release/bundle/nsis/RagVault_2.1.0_x64-setup.exe` (~170 MiB)

> The same file is attached to the
> [alpha-v2.1 release](https://github.com/kitief/Rag-retrieve/releases/tag/alpha-v2.1)
> (the repository is private, so downloading it needs a GitHub login).
> If the repo only contains `RagVault_1.3.0_x64-setup.exe`, that is the previous
> alpha — it predates the layered PDF
> parsing and the persisted connection state described here.

**Building from source** (needs the Rust MSVC toolchain, Python 3.11 and Node 20+):

```powershell
# 1) Frontend first — the spec packs frontend\dist into the frozen output
cd frontend; npm run build
# 2) Freeze the backend (~5 min, ~406 MB output)
.venv-desktop\Scripts\pyinstaller backend\ragvault-backend.spec
# 3) Build the installer (needs a proxy for the first NSIS download)
$env:https_proxy="http://127.0.0.1:7897"
frontend\node_modules\.bin\tauri build
```

> Step 2 collects `frontend/dist` into
> `dist\ragvault-backend\_internal\frontend\dist`, so the frontend must be built
> first. After a frontend change, just rerun steps 2 and 3 — there is nothing to
> copy by hand.

The full design trade-offs, pitfalls and acceptance checklist are in
[docs/desktop-packaging.md](docs/desktop-packaging.md) (Chinese).

Runtime shape:

| | Desktop |
| --- | --- |
| Database | SQLite (WAL) |
| Vector store | Embedded Chroma (PersistentClient) |
| Startup | Double-click the exe |
| Data location | `%APPDATA%\com.ragvault.desktop\data` |
| Install location | `%LOCALAPPDATA%\RagVault` |
| Upload cap | 500 MB |
| Access | Native window (backend listens on loopback only) |

---

## 🏗 Architecture

```
Tauri v2 shell (Rust)
   │  generates RAGVAULT_LOCAL_TOKEN, spawns the backend, parses RAGVAULT_READY port=…
   ▼
WebView2 window (React + Vite, served by the backend)
   │  REST + SSE  │
   ▼               ▼
FastAPI Backend (single Python process, bound to 127.0.0.1)
   ├── Auth (JWT)
   ├── Ingestion Service
   │    └── PDF/PPTX/Word/TXT/MD/Image/Video/Audio → Parse → Chunk → Embed → ChromaDB
   ├── RAG Service (LangGraph)
   │    └── Question → Embed → Retrieve → LLM → Answer + Citations  (SSE streaming)
   ├── Quiz Service
   │    └── LLM generates MCQs in parallel batches → grade → weak topics
   ├── Notes Service
   │    └── LLM generates page-by-page study cards → downloadable PDF
   └── Recommendation Service
        └── LangGraph → LLM → personalised Markdown study plan
   │
   ├── SQLite (%APPDATA%\com.ragvault.desktop\data\ragvault.db — users, chats, messages, documents, quizzes, notes)
   ├── Embedded ChromaDB 0.5.18 (%APPDATA%\com.ragvault.desktop\data\chroma, per chat_id collection)
   └── Cloud LLM (OpenAI-compatible Chat Completions API — DeepSeek by default)
```

### LLM Provider

`backend/app/services/llm_client.py` is the single place that talks to a model
provider. It speaks the OpenAI Chat Completions protocol, with a provider preset
table:

| `LLM_PROVIDER` | Default base URL | Default model | Key env var |
|---|---|---|---|
| `deepseek` | `https://api.deepseek.com/v1` | `deepseek-chat` | `LLM_API_KEY` |
| `openai` | `https://api.openai.com/v1` | `gpt-4o-mini` | `LLM_API_KEY` |
| `custom` | *(from `LLM_BASE_URL`)* | *(from `LLM_MODEL`)* | `LLM_API_KEY` |

Explicit `LLM_BASE_URL` / `LLM_MODEL` values always win over the preset, so any
OpenAI-compatible gateway (Azure OpenAI, Moonshot, Qwen, a self-hosted vLLM, …)
works by setting `LLM_PROVIDER=custom`.

Features: token streaming for chat SSE, `response_format=json_object` for the
notes generator, automatic retry with exponential backoff on 429/5xx, and a
startup probe that only logs a warning when the key is missing (the API still
boots and `/health` stays green).

> The old local stack (`model-init` + `llm` llama.cpp services, `app/utils/ollama_helper.py`,
> `app/services/llm_gate.py`, the LangChain `Ollama` clients) has been removed.
> `scripts/setup_model.py` and `models/*.gguf` are no longer used.

---

## 🌐 Language (English / 简体中文)

Everything the user reads — the web UI, validation errors, and the answers the
model writes — can be switched between **English** and **Simplified Chinese**.

### Built-in default

Tick `Use as deployment default` under Settings → Language, or set the `APP_LANGUAGE`
environment variable (`zh` / `en`, default `en`). The value is exposed to the UI by
`GET /config` (`default_language`), so a fresh install starts in that language.

### Per-visitor override

The language switcher sits in the sidebar footer, next to the dark/light toggle
(collapsed to a single globe button when the sidebar is narrow). A choice made
there is stored in `localStorage` (`ragvault-language-preference`) and wins over
`APP_LANGUAGE` for that browser only — handy for a shared machine or when you
want to demo both locales.

### How the language reaches the backend

1. `src/api/client.ts` adds an `X-App-Language: en|zh` header to every axios
   request, and `src/api/messages.ts` does the same on the SSE `fetch`, so
   streamed answers follow the UI.
2. `app/main.py` wraps the ASGI app in `LanguageMiddleware`, which stores the
   header value in a `contextvars.ContextVar` (bare ASGI middleware, so the value
   survives while a streaming response body is being consumed).
3. `app/core/i18n.py` resolves the language per request
   (`X-App-Language` → `APP_LANGUAGE` → `en`) and provides:
   - `t("chat.not_found")` for API error details,
   - `prompt_language_directive()` appended to every LLM prompt so the model
     answers in the active language (prompts themselves stay in English),
   - language-aware PDF export: the notes PDFs are laid out with PyMuPDF's
     `Story` engine, which wraps CJK text by width and falls back to a bundled
     font for Chinese glyphs (the built-in Helvetica has none), then subsets the
     embedded font so a one-page summary stays around 30 KB.

Nothing is cached across requests, so two browsers can use different languages
at the same time.

### Adding a language

1. Add the code to `SUPPORTED_LANGUAGES` in `frontend/src/i18n/index.ts` (and
   to `SUPPORTED_LANGUAGES` in `backend/app/core/i18n.py`).
2. Copy the `zh` table in `frontend/src/i18n/messages.ts` and translate it —
   `tsc` fails if a key is missing, because `zh` is typed as
   `Record<MessageKey, string>`.
3. Copy the `zh` block in `backend/app/core/i18n.py`; drop a matching date-fns
   locale into `useDateLocale()`.

---

## 📁 Supported File Types

| Type | Extensions | Status | Processing |
|------|-----------|--------|------------|
| PDF | `.pdf` | ✅ active | Layered pipeline: audit every page first, OCR only the bad ones (RapidOCR, models ship with the wheel); tables become Markdown |
| PowerPoint | `.pptx` `.ppt` | ✅ active | python-pptx slide-by-slide; binary `.ppt` fallback via raw stream extraction |
| Word (modern) | `.docx` | ✅ active | python-docx, body order preserved, tables flattened to `a \| b`; ZIP-XML fallback |
| Word (legacy) | `.doc` | ✅ active | Pure-Python OLE2 + Word piece table (`app/utils/doc_legacy.py`); RTF/HTML mislabelled as `.doc` also handled |
| Markdown | `.md` `.markdown` | ✅ active | Direct read, source kept verbatim (headings, lists, code fences), split into ~2000-char pseudo-pages |
| Plain Text | `.txt` `.text` | ✅ active | Direct read with UTF-8 / GB18030 / UTF-16 fallback; blank-line paragraphs, per-line when a file has none |
| Delimited | `.csv` `.tsv` | ✅ active | Row-aware pages — the header is repeated on every pseudo-page so a chunk still names its columns |
| Image | `.png` `.jpg` `.jpeg` `.webp` `.bmp` `.tiff` | 🅿️ shelved | Tesseract OCR with contrast enhancement — needs `ENABLE_OCR_UPLOADS=true` |
| Video | `.mp4` `.mkv` `.mov` `.avi` `.webm` | 🅿️ shelved | ffmpeg audio extract → Faster-Whisper — needs `ENABLE_AUDIO_VIDEO_UPLOADS=true` |
| Audio | `.mp3` `.wav` `.m4a` `.ogg` `.flac` `.aac` | 🅿️ shelved | Faster-Whisper (PyAV fallback) — needs `ENABLE_AUDIO_VIDEO_UPLOADS=true` |

> ❌ Anything outside the active set is rejected with a clear 422 error message.
> 📦 Maximum upload size: **500 MB** per file.

### Why `.doc` needs no extra dependency

`python-docx` only opens the OOXML zip container, so it cannot read Word 97-2003
files at all. The alternatives were all unattractive for a desktop app that ships
as an offline PyInstaller bundle: `olefile` is another dependency to vendor,
COM automation needs a licensed Word install on the target machine, and
`textract`/`antiword` bring native binaries. `backend/app/utils/doc_legacy.py`
therefore implements the two small, stable formats involved — the Compound File
Binary container and the Word piece table — in about 400 lines of pure Python.
Damaged or mislabelled files (RTF or HTML renamed to `.doc`, plain text with a
Word extension) are detected and routed to a suitable fallback instead of
failing the upload.

### PDF: audit first, parse second

Most "I uploaded a PDF and it cannot answer" reports are not a broken parser —
the pages simply have no text layer. The page is one big scan, so PyMuPDF reads
an empty string or a few dozen stray glyphs. The old implementation dropped such
pages silently, so the document showed as *ready* while only a handful of
fragments reached the index, and the model could only reply "not in your
documents".

`backend/app/utils/pdf_pipeline.py` splits this into two steps:

1. **Audit** (fast, no OCR budget spent). Every page is measured for text volume,
   image coverage, junk-character ratio and single-character lines, scored 0–1
   for quality, then classified `digital` / `scanned` / `hybrid` / `blank` and
   flagged `needs_ocr`. The decisive signal for a bad page is **a page-sized
   image carrying almost no text** — the signature of a scan hiding a poor OCR
   layer.
2. **OCR on demand.** Only pages flagged `needs_ocr` are rasterised and read, and
   preprocessing is a ladder (original → deskew → denoise+binarise → combined)
   that stops at the first acceptable confidence, because binarising an already
   clean page measurably hurts recognition.

Pages that were skipped are **reported, not swallowed**: the document row carries
a `parse_audit`, the list shows "OCR n pages" / "m pages unread" badges, and the
dialog breaks that down per page with character count, OCR confidence and the
preprocessing step used. "Why can't it answer" becomes inspectable instead of a
guess.

Two failure modes no longer pass silently either: a scanned file whose OCR is
switched off (or whose machine has no OCR engine at all) now **fails the upload
with a reason** instead of indexing zero chunks and reporting "ready", and the
reason is stored on the document row as `error_message` and shown in the list.

Three deliberate tradeoffs:

- **No parallel OCR, but the thread count is capped.** onnxruntime opens one
  thread per logical core by default, and on a loaded machine those threads fight
  for cores: measured on the same pages, the library default took 12.4 s/page and
  a cap of 8 took 7.5 s/page. A process pool measured a bit faster still
  (6.1 s/page), but a packaged build would then need `freeze_support()` and a
  controlled entry point, so the gain did not justify the risk. Long documents are
  therefore bounded by `PDF_OCR_MAX_PAGES` and `PDF_OCR_TIME_BUDGET_SECONDS`, with
  the thread count set by `PDF_OCR_THREADS`.
- **A page with a real text layer is never OCRd.** The text layer is exact; OCR
  could only be worse.
- **300 DPI with the long edge capped at 1600 is enough.** At 400 DPI the
  character count and confidence were identical — just slower.

A 1400-page scanned book takes hours to OCR end to end (measured: 4.5s per page,
about 107 minutes for 1439 pages). `PDF_OCR_MAX_PAGES` defaults to `0`
(unlimited); for books like that, set it to a few hundred or upload in parts.
When OCR is truncated the audit says how many pages were left unread, and
questions about those pages still get an honest "not found" rather than an
invented answer.

### Re-enabling a shelved parser

Image OCR and audio/video transcription keep their code but stay gated. (PDF OCR
is on by default, so it is not covered here.)

1. un-comment `pytesseract` / `faster-whisper` in `backend/requirements.txt`
2. install the system components: Tesseract-OCR (with the `chi_sim` language pack) and ffmpeg
3. set `ENABLE_OCR_UPLOADS` / `ENABLE_AUDIO_VIDEO_UPLOADS` to true in `.env`
4. (optional) add the extensions back to `SUPPORTED_EXTS` in
   `frontend/src/components/documents/DropZone.tsx`

---

## 🖥 Technology Stack

| Layer | Technology |
|-------|-----------|
| Frontend | React 18 + Vite + TypeScript + Tailwind CSS + shadcn/ui |
| Animations | Framer Motion + Three.js |
| State | TanStack Query v5 + Zustand v5 |
| Backend | FastAPI + LangGraph |
| LLM | **Cloud API** over OpenAI-compatible Chat Completions (DeepSeek by default) |
| Default Model | `deepseek-chat` (configurable via `LLM_PROVIDER` / `LLM_MODEL`) |
| Embeddings | **FastEmbed** (ONNX Runtime) — `BAAI/bge-small-en-v1.5` |
| Vector DB | ChromaDB 0.5.18 (embedded `PersistentClient`) |
| Relational DB | SQLite (WAL mode) |
| Desktop shell | Tauri v2 (Rust) + WebView2 |
| Packaging | PyInstaller (backend) + NSIS (installer) |
| Speech-to-Text | *Shelved* — Faster-Whisper code kept, disabled by default |
| OCR | **RapidOCR** (ONNX export of PaddleOCR) — PDF scans only, on demand |
| Auth | JWT (access + refresh tokens), bcrypt |

No deviations from the specified stack were made.

---

## ⚙️ Configuration

Day-to-day use needs no configuration file at all — the API key, language and model live in
the in-app Settings dialog and are stored in `%APPDATA%\com.ragvault.desktop\data\ragvault.db`. The environment
variables below are only the built-in defaults, overridable from `.env` during development
(see `.env.example`):

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_PROVIDER` | `deepseek` | `deepseek` / `openai` / `custom` |
| `LLM_API_KEY` | *(empty)* | Provider API key — leave blank and enter it in the app |
| `LLM_MODEL` | `deepseek-chat` | Model identifier sent to the provider |
| `LLM_BASE_URL` | `https://api.deepseek.com/v1` | OpenAI-compatible base URL (overrides the preset) |
| `LLM_TIMEOUT_SECONDS` | `180` | Per-request timeout |
| `LLM_MAX_RETRIES` | `3` | Retries on 429 / 5xx / transport errors |
| `APP_LANGUAGE` | `en` | Built-in default UI + AI language (`en` / `zh`) |
| `ENABLE_AUDIO_VIDEO_UPLOADS` | `false` | Shelved audio/video transcription |
| `ENABLE_OCR_UPLOADS` | `true` | OCR for PDF scans; also unlocks the shelved image OCR |
| `PDF_OCR_ENGINE` | `auto` | `auto` / `rapidocr` / `tesseract` — `auto` prefers RapidOCR |
| `PDF_OCR_DPI` | `300` | Rasterisation DPI; higher does not improve accuracy, only cost |
| `PDF_OCR_MAX_SIDE` | `1600` | Long-edge cap on the rendered image, to bound CPU |
| `PDF_OCR_MAX_PAGES` | `0` | Max pages OCRd per document (`0` = unlimited); keep it small for long scans |
| `PDF_OCR_TIME_BUDGET_SECONDS` | `1800` | Per-document OCR budget; on expiry OCR stops and unread pages are recorded |
| `PDF_OCR_MIN_CONFIDENCE` | `0.75` | Pages below this are flagged low-confidence for review |
| `PDF_OCR_MAX_ATTEMPTS` | `3` | Preprocessing ladder depth (original → deskew → binarise → combined) |
| `PDF_OCR_THREADS` | `8` | ONNX threads for OCR. Measured: library default (one per core) 12.4 s/page, capped at 8 → 7.5 s/page; `0` hands the choice back to the library |
| `PDF_MIN_TEXT_CHARS` | `200` | A page-sized image with less text than this is treated as needing OCR |
| `PDF_EXTRACT_TABLES` | `true` | Convert PDF tables to Markdown and index them too |
| `EMBEDDING_MODEL` | `BAAI/bge-small-en-v1.5` | FastEmbed ONNX embedding model |
| `WHISPER_MODEL` | `base` | Only used if audio/video is re-enabled |
| `CHUNK_SIZE` | `600` | Target tokens per chunk |
| `CHUNK_OVERLAP` | `100` | Token overlap between chunks |
| `TOP_K` | `5` | Number of chunks to retrieve per query |
| `WHISPER_DEVICE` | `cpu` | Set to `cuda` if GPU available |
| `DATA_DIR` | `%APPDATA%\com.ragvault.desktop\data` | Root for all mutable data (DB, vectors, uploads, model cache) |
| `JWT_SECRET` | *(built-in default)* | Random 32+ char string for JWT signing |

---

## 🚀 Usage Guide

### Creating a Knowledge Space

1. Click **"+ New Chat"** in the sidebar
2. Give it a name (e.g., "Machine Learning Finals")
3. Upload your documents via drag-and-drop or click to browse

### Chatting with Your Documents

- Type questions in the chat input and press **Enter** or **Ctrl+Enter**
- Answers stream token-by-token in real time via SSE with source citations (filename + page number)
- Citations are strictly grounded — the LLM cannot invent sources

### Generating a Quiz

1. Open the **Quiz** tab in the right panel
2. Enter a topic (e.g., "neural networks") and choose number of questions
3. Click **Generate Quiz** — the LLM creates MCQs from relevant document chunks in parallel batches
4. Submit answers to see your score, explanations, and weak topics
5. Click **Get Recommendations** for a personalized Markdown study plan based on your last 5 quiz results

### AI Notes

1. Open the **Notes** tab in the right panel
2. Click **Generate Notes** — the LLM creates structured page-by-page study cards for all uploaded documents
3. Download as a **searchable PDF** via the PDF download button
4. After submitting a quiz, generate **Remedial Notes** targeting only the concepts you got wrong (also downloadable as PDF)

### Adding More Documents

Upload new documents to an existing chat — they accumulate in the knowledge base. Use **"Clear Knowledge"** to wipe all vectors and start fresh without deleting the chat.

### Renaming or Deleting a Knowledge Space

- Chats auto-title themselves after the first question using the LLM
- Rename via the PATCH chat endpoint or from the UI
- Delete a chat (purges messages, documents, quizzes, notes, and vector collection)

---

## 🛠 Development Setup

Pick one of two ways to run the app before writing code — they differ a lot in startup cost:

| Mode | Command | Best for | Hot reload |
| --- | --- | --- | --- |
| **Single process + Vite** (recommended) | `.\scripts\dev.cmd` | Day-to-day backend and frontend work | Both |
| Desktop shell | `npm run tauri dev` | Native save dialog, first-run prompt, drag and drop | None — rebuild the frontend |

### One-time setup

```powershell
# Backend dependencies
python -m venv .venv-desktop
.venv-desktop\Scripts\pip install -r backend\requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# Frontend dependencies
cd frontend
npm install --registry https://registry.npmmirror.com
```

### Daily work: `scripts\dev.cmd`

```powershell
.\scripts\dev.cmd                 # API + Vite, both hot reloading
.\scripts\dev.cmd -BackendOnly    # API only (also serves the built SPA)
.\scripts\dev.cmd -NoReload       # Disable reload; use when debugging with breakpoints
.\scripts\dev.cmd -Frozen         # Run the PyInstaller bundle — same binary as the installer
.\scripts\dev.cmd -Stop           # Stop every related process
```

The script brings the API up on `http://127.0.0.1:8000` with `--reload` (any change under `backend/` restarts it), then starts Vite on `http://127.0.0.1:3000`, where `/api` is proxied to the backend by `vite.config.ts`. Data goes to `.desktop-data\` (SQLite + embedded Chroma), completely separate from the installed app's data in `%APPDATA%\com.ragvault.desktop\data`.

> **Why the entry point is `.cmd` and not `.ps1`**
>
> `dev.ps1` is not code-signed. Under the default `RemoteSigned` policy a locally
> authored script is normally allowed to run — but if the Authenticode
> verification path is restricted by security software or group policy, invoking
> `.\scripts\dev.ps1` directly fails with "not digitally signed" or
> "AuthorizationManager check failed".
>
> `dev.cmd` is not a PowerShell script, so the execution policy never applies to
> it. It re-launches `dev.ps1` with `-ExecutionPolicy Bypass` **scoped to that
> single child process** — no registry key is written, no machine-wide setting
> changes, and the policy reverts as soon as the child exits. Arguments are
> forwarded verbatim, so both files are used identically.
>
> To relax the policy permanently instead (optional, admin required):
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` — though on a locked-down
> machine that usually will not take effect either, which is why `dev.cmd` is the
> simpler route.

> The ports live in `vite.config.ts` (3000 and 8000). `-ApiPort` / `-WebPort` only change the backend listener, not the proxy target, and the script warns about it.

### Testing the desktop shell

```powershell
# Run from the repository root: the tauri CLI only searches downwards for
# tauri.conf.json, so running it inside frontend\ fails with
# "Couldn't recognize the current folder as a Tauri project".
.\frontend\node_modules\.bin\tauri dev      # ~2 min for the first Rust build
```

The shell starts the backend itself and injects `RAGVAULT_LOCAL_TOKEN`, so anything that only exists on the desktop side (native save dialog, first-run prompt, drag and drop) has to be tested here — a browser will never show it.

`tauri dev` does not reload the frontend: the window loads the built bundle from `frontend\dist\`, so re-run `npm run build` and restart the shell. For everyday UI work the Vite server behind `dev.ps1` is much faster.

---

## ⚙️ In-App Settings

Click your avatar at the bottom of the sidebar (or press `Ctrl+,`) to open the
settings dialog. It has two groups:

| Group | What it does |
| --- | --- |
| **Language** | Switches the interface, validation messages and AI answers between English and 中文 for the current browser. `Use as deployment default` also stores the choice as the default for new visitors. |
| **API** | Pick a provider (DeepSeek / OpenAI / any OpenAI-compatible endpoint), fill in the base URL and the API key, then press **Connect**. Connecting probes `GET /v1/models` with the credentials currently in the form and only then unlocks the model field, pre-filling it with the first model the endpoint advertises. Until a probe succeeds the model field stays empty and the status strip is red; a successful probe turns it green. Keys can be pasted straight into the input, and the key menu beside it saves, switches and deletes stored credentials. |

**The connection state persists.** The probe result — whether it succeeded, the model list, and a fingerprint of the endpoint and key it was measured against — lives in the `llm_connection` row of `app_settings`, so closing and reopening the dialog restores the same green badge and model list instead of asking you to prove again what the backend already knows. The secret itself is never written to that row; only a masked hint like `sk-…128e`.

A green badge does not stay green forever. As soon as the base URL, the provider or the key differs from what was measured, the API marks the record `stale`, the UI treats it as "not connected" and shows red. Editing the configuration without re-probing never leaves a stale green light behind. Below the theme toggle in the sidebar there is also a connection shortcut: green means the current configuration works (it shows the model in use), red means there is no working connection, and clicking it jumps straight to the API panel.

### Saved API keys

The **API** panel keeps a small key vault (`llm_api_keys` table) so several
credentials can coexist and be swapped without retyping them:

| Action | Effect |
| --- | --- |
| Type a key + label → **Save key** | Stores the key and activates it immediately |
| **Saved keys** dropdown | Switches the active credential; the choice applies to the very next request |
| Trash icon | Deletes the currently active key |

Exactly one key is active at a time — it is mirrored into `app_settings.llm_api_key`
so the request path stays a single dict lookup. Keys are write-only over the API:
responses only ever contain a masked hint such as `sk-…1a2b`.

Values are stored in the `app_settings` table, so they **survive restarts and
override the built-in defaults** — no file edit is needed. Only the retrieved
document snippets are sent to the provider; embeddings stay local.

`Restore defaults` in the dialog footer deletes every stored override so the
built-in defaults apply again.

---

## 🧪 Running Tests

The test suite is not part of the runtime artifacts, so install the extra
dependencies first:

```bash
# Backend tests
cd backend
pip install -r requirements-dev.txt
pytest tests/ -v --tb=short

# Frontend lint
cd frontend
npm run lint
```

The fixture in `backend/tests/conftest.py` uses in-memory SQLite, so no external
service is required.

---

## 🔧 Running & Troubleshooting

Desktop logs are forwarded by the Tauri shell to the console that launched it; during
development, `scripts\dev.cmd` shows the backend output directly.

```powershell
.\scripts\dev.cmd -Stop     # Stop every related process (backend + Vite)

# Data directory (delete to factory-reset)
Remove-Item -Recurse "$env:APPDATA\com.ragvault.desktop"
```

---

## 📊 API Reference
The API is documented at `http://localhost:8000/docs` (Swagger UI) and `http://localhost:8000/redoc` after startup.

**Core endpoints:**

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/auth/register` | Register new user |
| `POST` | `/auth/login` | Login, get JWT tokens |
| `GET` | `/chats` | List all knowledge spaces |
| `POST` | `/chats` | Create new knowledge space |
| `GET` | `/chats/{id}` | Get a single knowledge space |
| `PATCH` | `/chats/{id}` | Rename a knowledge space |
| `DELETE` | `/chats/{id}` | Delete a knowledge space (purges all data) |
| `POST` | `/chats/{id}/documents` | Upload + ingest document (async, returns 202) |
| `GET` | `/chats/{id}/documents` | List documents and their processing status |
| `DELETE` | `/chats/{id}/documents/{doc_id}` | Delete a single document and its vectors |
| `POST` | `/chats/{id}/messages` | Ask a question (SSE streaming or JSON) |
| `GET` | `/chats/{id}/messages` | Get chat history |
| `DELETE` | `/chats/{id}/messages` | Clear all messages |
| `DELETE` | `/chats/{id}/messages/{msg_id}` | Delete a single message |
| `POST` | `/chats/{id}/quiz` | Generate quiz (MCQs from documents) |
| `GET` | `/chats/{id}/quiz-history` | List all past quizzes for a space |
| `POST` | `/quiz/{id}/submit` | Submit quiz answers, get score + weak topics |
| `GET` | `/chats/{id}/recommendations` | Get personalized study plan (LangGraph) |
| `POST` | `/chats/{id}/notes` | Generate AI study note cards |
| `GET` | `/chats/{id}/notes` | Fetch latest AI notes |
| `GET` | `/chats/{id}/notes/pdf` | Download AI notes as PDF |
| `POST` | `/chats/{id}/quiz-remedial-notes` | Generate remedial notes for missed questions |
| `GET` | `/chats/{id}/quiz-remedial-notes` | Fetch latest remedial notes |
| `GET` | `/chats/{id}/quiz-remedial-notes/pdf` | Download remedial notes as PDF |
| `POST` | `/chats/{id}/clear-knowledge` | Wipe all vectors + documents for a chat |
| `GET` | `/health` | Health check (`{"status": "ok"}`) |

---

## 🗂 Project Structure

```
RagVault/
├── frontend/               # React + Vite + TypeScript (build output served by the backend)
│   ├── src/
│   │   ├── api/            # TanStack Query hooks
│   │   ├── components/     # UI components (shadcn/ui + custom)
│   │   ├── pages/          # Route pages
│   │   ├── store/          # Zustand stores
│   │   ├── types/          # TypeScript types
│   │   ├── lib/desktop.ts  # Local API token / native save dialog
│   │   └── theme.ts        # Design system tokens
│   └── vite.config.ts
├── backend/                # FastAPI application (single process, also serves the SPA)
│   ├── app/
│   │   ├── models/         # SQLAlchemy ORM (user, chat, document, message, quiz, note, memory)
│   │   ├── schemas/        # Pydantic schemas
│   │   ├── routers/        # FastAPI routers (auth, chats, documents, messages, quiz, notes)
│   │   ├── services/       # Business logic (rag, quiz, notes, ingestion, recommendation, auth)
│   │   ├── utils/          # Parsers, chunker, FastEmbed embedder, ChromaDB client
│   │   ├── core/           # Auth dependencies, security, i18n, SPA hosting
│   │   ├── desktop_boot.py # Desktop launcher: data dir, port, RAGVAULT_READY
│   │   └── main.py
│   ├── tests/              # pytest (in-memory SQLite)
│   └── ragvault-backend.spec   # PyInstaller build config
├── src-tauri/              # Tauri v2 shell (Rust)
│   ├── src/
│   ├── tauri.conf.json
│   └── Cargo.toml
├── scripts/
│   ├── dev.cmd             # Day-to-day entry point (bypasses script policy)
│   ├── dev.ps1             # Actual startup logic: backend + Vite
│   ├── run_desktop.py      # Single-process entry point
│   └── prepare_embedded_models.py
├── docs/desktop-packaging.md
└── .env.example            # Development only — the installer reads no env file
```

---

## 🎮 Remote / Self-Hosted LLM (Optional)

Since answer generation is a plain OpenAI-compatible HTTP call, you can point
RagVault at any compatible server instead of DeepSeek — including a local
vLLM / llama.cpp / Ollama gateway on another machine:

```bash
LLM_PROVIDER=custom
LLM_BASE_URL=http://192.168.1.10:11434/v1
LLM_MODEL=qwen2.5:7b-instruct
LLM_API_KEY=not-needed-but-must-be-non-empty
```

`LLM_API_KEY` must be a non-empty string even for keyless local servers,
because the client refuses to send unauthenticated requests.

---

## 📝 License

MIT License. See [LICENSE](LICENSE) for details.

This release (`alpha-v1.3`) is derived from the original
[RagVault](https://github.com/Meet-paladiya/RagVault) project by Meet Paladiya.
The upstream history is intentionally not carried over; this repository starts
from a single `alpha-v1.1` commit, adds the settings dialog in `alpha-v1.2`, and
adds the Windows desktop build (Tauri v2 shell + PyInstaller backend, see
[docs/desktop-packaging.md](docs/desktop-packaging.md)) in `alpha-v1.3`.

---

> **Note to contributors:** Answer generation is centralized in
> `backend/app/services/llm_client.py` — add new AI features by calling
> `chat_completion()` / `stream_chat_completion()` there rather than importing a
> provider SDK directly, so the provider stays swappable via `.env`.
