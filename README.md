# RagVault

> Self-Hosted · RAG-Powered AI Learning System · Cloud LLM + Local Embeddings
>
> **Release `alpha-v1.2`** · Repository: <https://github.com/kitief/Rag-retrieve>

A self-hosted Retrieval-Augmented Generation (RAG) learning platform for students. Upload PDF and PPTX files to create "knowledge spaces," then ask questions, generate quizzes, create AI study notes, track weak topics, and get personalized study recommendations.

All **answer generation** is delegated to a cloud LLM over an OpenAI-compatible API (**DeepSeek** by default, any compatible endpoint supported). **Embeddings stay local** via FastEmbed ONNX, so your documents are only ever reduced to embeddings on your own machine — only the retrieved snippets are sent to the model provider.

---

## ⚡ Quick Start

### Prerequisites

| Tool | Version | Notes |
|------|---------|-------|
| Docker | 24.0+ | |
| Docker Compose | 2.20+ | |
| RAM | 8GB minimum | Postgres + Chroma + backend + frontend |
| Disk | 3GB free | Python + Node images plus data volumes |
| LLM API key | — | DeepSeek: https://platform.deepseek.com/api_keys |

### 1. Clone & Configure

```bash
git clone https://github.com/kitief/Rag-retrieve.git
cd Rag-retrieve
cp .env.example .env
```

Edit `.env` with at minimum:
```bash
POSTGRES_PASSWORD=your_strong_password
JWT_SECRET=your_random_32_char_secret_here
LLM_API_KEY=sk-...            # required — chat, quizzes, notes all need it
LLM_PROVIDER=deepseek         # or: openai | custom
```

If you use a non-DeepSeek provider, also set:
```bash
LLM_BASE_URL=https://your-endpoint/v1
LLM_MODEL=your-model-name
```

### 2. Start All Services

```bash
docker compose up -d
```

This starts **4 services**: `postgres`, `chromadb`, `backend`, `frontend`.
There is no local model server and no GGUF download.

### 3. Open the App

```
http://localhost:3000
```

Register an account, create a Knowledge Space, upload documents, and start learning!

> ⚠️ Internet is required at runtime for LLM inference (the provider API), and on first start to pull Docker images and the FastEmbed ONNX model.

---

## 🏗 Architecture

```
Browser (React + Vite)
   │  REST + SSE  │
   ▼               ▼
FastAPI Backend (port 8000)
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
   ├── PostgreSQL (users, chats, messages, documents, quizzes, notes)
   ├── ChromaDB 0.5.18 (vector embeddings, per chat_id collection)
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
> `scripts/setup_model.py` and `models/*.gguf` are no longer used by compose.

---

## 🌐 Language (English / 简体中文)

Everything the user reads — the web UI, validation errors, and the answers the
model writes — can be switched between **English** and **Simplified Chinese**.

### Deployment default

Set `APP_LANGUAGE` in `.env` and restart the backend:

```env
APP_LANGUAGE=zh     # zh = 简体中文, en = English (default)
```

`docker-compose.yml` forwards it to the backend container. It is exposed to the
browser by `GET /config` (`default_language`), so a fresh browser opening the app
starts in that language.

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
| PDF | `.pdf` | ✅ active | PyMuPDF page-by-page; scanned pages fall back to OCR only when `ENABLE_OCR_UPLOADS=true` |
| PowerPoint | `.pptx` `.ppt` | ✅ active | python-pptx slide-by-slide; binary `.ppt` fallback via raw stream extraction |
| Word | `.docx` `.doc` | 🅿️ shelved | python-docx / ZIP-XML fallback — parser kept, upload rejected |
| Plain Text | `.txt` `.md` `.csv` | 🅿️ shelved | Direct read, split into ~2000-char pseudo-pages — parser kept |
| Image | `.png` `.jpg` `.jpeg` `.webp` `.bmp` `.tiff` | 🅿️ shelved | Tesseract OCR with contrast enhancement — needs `ENABLE_OCR_UPLOADS=true` |
| Video | `.mp4` `.mkv` `.mov` `.avi` `.webm` | 🅿️ shelved | ffmpeg audio extract → Faster-Whisper — needs `ENABLE_AUDIO_VIDEO_UPLOADS=true` |
| Audio | `.mp3` `.wav` `.m4a` `.ogg` `.flac` `.aac` | 🅿️ shelved | Faster-Whisper (PyAV fallback) — needs `ENABLE_AUDIO_VIDEO_UPLOADS=true` |

> ❌ Anything outside the active set is rejected with a clear 422 error message.
> 📦 Maximum upload size: **2 GB** per file.

### Re-enabling a shelved parser

The parsing code is *kept in full* at `backend/app/utils/parsers.py`; only the
entry points are gated. To bring one back:

1. set `ENABLE_OCR_UPLOADS=true` and/or `ENABLE_AUDIO_VIDEO_UPLOADS=true` in `.env`
2. un-comment `pytesseract` / `faster-whisper` in `backend/requirements.txt`
3. un-comment the `tesseract-ocr` / `ffmpeg` `apt-get` block in `backend/Dockerfile`
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
| Vector DB | ChromaDB 0.5.18 (persistent local) |
| Relational DB | PostgreSQL 16 |
| Speech-to-Text | *Shelved* — Faster-Whisper code kept, disabled by default |
| OCR | *Shelved* — Tesseract code kept, disabled by default |
| Auth | JWT (access + refresh tokens), bcrypt |
| Deployment | Docker + Docker Compose |

No deviations from the specified stack were made.

---

## ⚙️ Configuration

All configuration is in `.env`. Key variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_PROVIDER` | `deepseek` | `deepseek` / `openai` / `custom` |
| `LLM_API_KEY` | *(must set)* | Provider API key — chat, quizzes, notes, titles all need it |
| `LLM_MODEL` | `deepseek-chat` | Model identifier sent to the provider |
| `LLM_BASE_URL` | `https://api.deepseek.com/v1` | OpenAI-compatible base URL (overrides the preset) |
| `LLM_TIMEOUT_SECONDS` | `180` | Per-request timeout |
| `LLM_MAX_RETRIES` | `3` | Retries on 429 / 5xx / transport errors |
| `APP_LANGUAGE` | `en` | Deployment default UI + AI language (`en` / `zh`) |
| `ENABLE_AUDIO_VIDEO_UPLOADS` | `false` | Shelved audio/video transcription |
| `ENABLE_OCR_UPLOADS` | `false` | Shelved image / scanned-PDF OCR |
| `EMBEDDING_MODEL` | `BAAI/bge-small-en-v1.5` | FastEmbed ONNX embedding model |
| `WHISPER_MODEL` | `base` | Only used if audio/video is re-enabled |
| `CHUNK_SIZE` | `600` | Target tokens per chunk |
| `CHUNK_OVERLAP` | `100` | Token overlap between chunks |
| `TOP_K` | `5` | Number of chunks to retrieve per query |
| `WHISPER_DEVICE` | `cpu` | Set to `cuda` if GPU available |
| `POSTGRES_PASSWORD` | *(must set)* | PostgreSQL password |
| `JWT_SECRET` | *(must set)* | Random 32+ char string for JWT signing |

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

```bash
# Backend (Python 3.11)
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload

# Frontend (Node 20)
cd frontend
npm install
npm run dev
```

Backend runs on `http://localhost:8000`, frontend on `http://localhost:3000` (with proxy to backend).

---

## ⚙️ In-App Settings

Click your avatar at the bottom of the sidebar (or press `Ctrl+,`) to open the
settings dialog. It has two groups:

| Group | What it does |
| --- | --- |
| **Language** | Switches the interface, validation messages and AI answers between English and 中文 for the current browser. `Use as deployment default` also stores the choice as the default for new visitors. |
| **API** | Picks a provider from a dropdown (DeepSeek / OpenAI / any OpenAI-compatible endpoint), then sets the API key, base URL and model. The model field is a dropdown populated from the endpoint's `GET /v1/models`, with a manual-entry escape hatch. `Test connection` probes the endpoint without saving. |

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
override the matching `.env` entries** — no image rebuild is needed. Only the
retrieved document snippets are sent to the provider; embeddings stay local.

`Restore defaults` in the dialog footer deletes every stored override so the
`.env` configuration applies again.

---

## 🧪 Running Tests

The test suite is not part of the runtime image, so install the extra
dependencies first:

```bash
# Backend tests
cd backend
pip install pytest pytest-asyncio aiosqlite
pytest tests/ -v --tb=short

# Frontend lint
cd frontend
npm run lint
```

The fixture in `backend/tests/conftest.py` uses in-memory SQLite, so no
PostgreSQL or ChromaDB instance is required.

---

## 🔧 Service Management

```bash
# View logs
docker compose logs -f backend

# Restart a service
docker compose restart backend

# Full teardown (preserves data volumes)
docker compose down

# Full teardown + delete all data
docker compose down -v
```

### Optional: Nginx Reverse Proxy

An Nginx service is defined in `docker-compose.yml` but gated behind a Docker Compose profile. To enable it:

```bash
docker compose --profile nginx up -d
```

Nginx will serve on port 80 and proxy to both backend and frontend.

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
├── frontend/               # React + Vite + TypeScript
│   ├── src/
│   │   ├── api/            # TanStack Query hooks
│   │   ├── components/     # UI components (shadcn/ui + custom)
│   │   ├── pages/          # Route pages
│   │   ├── store/          # Zustand stores
│   │   ├── types/          # TypeScript types
│   │   └── theme.ts        # Design system tokens
│   ├── nginx.conf          # Production Nginx config for the frontend container
│   └── Dockerfile
├── backend/                # FastAPI application
│   ├── app/
│   │   ├── models/         # SQLAlchemy ORM (user, chat, document, message, quiz, note, memory)
│   │   ├── schemas/        # Pydantic schemas
│   │   ├── routers/        # FastAPI routers (auth, chats, documents, messages, quiz, notes)
│   │   ├── services/       # Business logic (rag, quiz, notes, ingestion, recommendation, auth)
│   │   ├── utils/          # Parsers, chunker, FastEmbed embedder, ChromaDB client
│   │   └── core/           # Auth dependencies, security
│   ├── alembic/            # DB migrations
│   └── Dockerfile          # python:3.11-slim + Tesseract + ffmpeg
├── models/                 # Legacy GGUF dir (no longer used by docker-compose)
├── docker/
│   └── nginx.conf          # Nginx reverse proxy config (optional profile)
├── docker-compose.yml      # 4 services (postgres, chromadb, backend, frontend)
└── .env.example            # Config template
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

This release (`alpha-v1.2`) is derived from the original
[RagVault](https://github.com/Meet-paladiya/RagVault) project by Meet Paladiya.
The upstream history is intentionally not carried over; this repository starts
from a single `alpha-v1.1` commit and adds the settings dialog in `alpha-v1.2`.

---

> **Note to contributors:** Answer generation is centralized in
> `backend/app/services/llm_client.py` — add new AI features by calling
> `chat_completion()` / `stream_chat_completion()` there rather than importing a
> provider SDK directly, so the provider stays swappable via `.env`.
