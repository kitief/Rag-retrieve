"""
Lightweight localisation layer for the backend.

Two things are localised here:

1. **User-visible strings** returning from the API (error details, PDF labels,
   generated titles).  Use :func:`t` instead of hard-coded English.
2. **LLM output language**.  Prompts stay written in English (models follow
   English instructions reliably), but a short :func:`language_directive` is
   appended so the model answers in the user's language.

The active language comes from, in order of precedence:

* the ``X-App-Language`` request header (the SPA sends whatever the user
  picked in the UI),
* a value saved from the settings dialog (``app_settings`` table),
* the ``APP_LANGUAGE`` environment variable (the Docker-level default),
* :data:`DEFAULT_LANGUAGE`.

Because the header is request-scoped, it is stored in a
:class:`contextvars.ContextVar` that the HTTP middleware in ``app.main`` sets
and resets around every request.  Background tasks inherit the context at
creation time, so they keep the language of the request that spawned them.
"""
from __future__ import annotations

import contextvars
from typing import Final

from app.config import get_settings
from app.core.runtime_settings import get_override

SUPPORTED_LANGUAGES: Final[tuple[str, str]] = ("en", "zh")
DEFAULT_LANGUAGE: Final[str] = "en"

# Human-readable names, used inside LLM directives.
LANGUAGE_DISPLAY_NAME: Final[dict[str, str]] = {
    "en": "English",
    "zh": "Simplified Chinese (简体中文)",
}

_ALIASES: Final[dict[str, str]] = {
    "en": "en",
    "en-us": "en",
    "en-gb": "en",
    "english": "en",
    "zh": "zh",
    "zh-cn": "zh",
    "zh-hans": "zh",
    "zh-sg": "zh",
    "cn": "zh",
    "chinese": "zh",
    "mandarin": "zh",
}

_current_language: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "ragvault_language", default=None
)


# ─── Language resolution ─────────────────────────────────────────────────────

def normalize_language(value: str | None) -> str | None:
    """Map arbitrary user input (``zh-CN``, ``cn``, ``中文``…) to a supported code."""
    if not value:
        return None
    code = str(value).strip().lower().replace("_", "-")
    if code in _ALIASES:
        return _ALIASES[code]
    base = code.split("-", 1)[0]
    return _ALIASES.get(base)


def configured_language() -> str:
    """
    Deployment default language.

    A value saved from the settings dialog wins over ``APP_LANGUAGE`` so the
    language can be changed without restarting the containers.
    """
    override = get_override("app_language")
    if override:
        normalized_override = normalize_language(override)
        if normalized_override:
            return normalized_override
    raw = getattr(get_settings(), "app_language", None)
    return normalize_language(raw) or DEFAULT_LANGUAGE


def current_language() -> str:
    """Language for the current request/task."""
    return _current_language.get() or configured_language()


def set_current_language(value: str | None) -> contextvars.Token:
    """Bind a language to the current context. Returns a token for :func:`reset_language`."""
    return _current_language.set(normalize_language(value) or configured_language())


def reset_language(token: contextvars.Token) -> None:
    try:
        _current_language.reset(token)
    except ValueError:
        # Token created in a different context (e.g. a copy_context child).
        _current_language.set(None)


def use_language(value: str | None) -> str:
    """Return the effective language, resolving ``value`` first (no context change)."""
    return normalize_language(value) or current_language()


# ─── Message catalogue ───────────────────────────────────────────────────────

MESSAGES: Final[dict[str, dict[str, str]]] = {
    # ── Auth ─────────────────────────────────────────────────────────────────
    "auth.email_exists": {
        "en": "An account with this email already exists.",
        "zh": "该邮箱已被注册。",
    },
    "auth.invalid_credentials": {
        "en": "Invalid email or password.",
        "zh": "邮箱或密码不正确。",
    },
    "auth.invalid_token_type": {
        "en": "Invalid token type — expected refresh token.",
        "zh": "令牌类型无效——需要刷新令牌。",
    },
    "auth.token_missing_identity": {
        "en": "Token payload missing user identity.",
        "zh": "令牌中缺少用户身份信息。",
    },
    "auth.could_not_validate": {
        "en": "Could not validate credentials",
        "zh": "无法验证登录凭证",
    },
    # ── Chat ownership ───────────────────────────────────────────────────────
    "chat.not_found": {
        "en": "Chat not found.",
        "zh": "会话不存在。",
    },
    "chat.access_denied": {
        "en": "Access denied.",
        "zh": "无权访问。",
    },
    "chat.title_empty": {
        "en": "Chat title cannot be empty.",
        "zh": "会话名称不能为空。",
    },
    # ── Documents ────────────────────────────────────────────────────────────
    "doc.not_found": {
        "en": "Document not found.",
        "zh": "文档不存在。",
    },
    "doc.too_large": {
        "en": "File size exceeds maximum allowed limit (2GB).",
        "zh": "文件大小超出上限（2GB）。",
    },
    "doc.unsupported_type": {
        "en": (
            "File type '{ext}' is not supported right now. "
            "Accepted types: PDF, PPTX/PPT. "
        ),
        "zh": (
            "暂不支持 '{ext}' 类型的文件。目前支持的类型：PDF、PPTX/PPT。"
        ),
    },
    "doc.still_processing": {
        "en": "A document is still being processed. Please wait until all uploads are ready.",
        "zh": "文档仍在解析中，请等待全部上传处理完成。",
    },
    "doc.none_uploaded": {
        "en": "No documents are uploaded in this chat. Open the chat where you uploaded the PDF.",
        "zh": "该会话中还没有上传文档，请先上传 PDF 或 PPTX。",
    },
    "doc.index_failed": {
        "en": "The uploaded documents could not be indexed. Please upload the PDF again.",
        "zh": "已上传的文档无法建立索引，请重新上传。",
    },
    "ingest.audio_shelved": {
        "en": "Audio transcription is currently disabled (ENABLE_AUDIO_VIDEO_UPLOADS=false).",
        "zh": "音频转写功能当前已暂停（ENABLE_AUDIO_VIDEO_UPLOADS=false）。",
    },
    "ingest.video_shelved": {
        "en": "Video transcription is currently disabled (ENABLE_AUDIO_VIDEO_UPLOADS=false).",
        "zh": "视频转写功能当前已暂停（ENABLE_AUDIO_VIDEO_UPLOADS=false）。",
    },
    "ingest.unsupported_extension": {
        "en": "Unsupported file extension: {ext}",
        "zh": "不支持的文件扩展名：{ext}",
    },
    # ── Notes ────────────────────────────────────────────────────────────────
    "notes.no_documents": {
        "en": "No documents found in this knowledge space. Please upload documents first.",
        "zh": "该知识空间中没有文档，请先上传文档。",
    },
    "notes.no_completed_quiz": {
        "en": "No completed quiz found. Please complete a quiz first to generate remedial notes.",
        "zh": "没有已完成的测验，请先完成一次测验再生成错题笔记。",
    },
    "notes.notes_required": {
        "en": "Generate AI notes before downloading the PDF.",
        "zh": "请先生成 AI 笔记，再下载 PDF。",
    },
    "notes.remedial_required": {
        "en": "Generate quiz remedial notes first before downloading the PDF.",
        "zh": "请先生成错题笔记，再下载 PDF。",
    },
    "notes.pdf_subtitle": {
        "en": "Complete page-by-page exam revision summary",
        "zh": "逐页完整复习摘要",
    },
    "notes.pdf_page_line": {
        "en": "{source} - Page {page}",
        "zh": "{source} - 第 {page} 页",
    },
    "notes.default_topic": {
        "en": "Key Concept {index}",
        "zh": "关键概念 {index}",
    },
    "notes.default_summary": {
        "en": "Overview of key concepts from material.",
        "zh": "本页核心概念概览。",
    },
    "notes.default_keypoint": {
        "en": "Key study point from document.",
        "zh": "文档中的关键学习要点。",
    },
    "notes.fallback_topic": {
        "en": "Page {page} Summary",
        "zh": "第 {page} 页摘要",
    },
    "notes.fallback_key_topic": {
        "en": "Key Topic {index}: {filename}",
        "zh": "关键主题 {index}：{filename}",
    },
    "notes.default_source": {
        "en": "Uploaded Document",
        "zh": "已上传文档",
    },
    "notes.title": {
        "en": "AI Notes: {chat}",
        "zh": "AI 笔记：{chat}",
    },
    "notes.remedial_title": {
        "en": "Quiz Remedial Notes: {topic}",
        "zh": "错题复习笔记：{topic}",
    },
    "notes.remedial_tag": {
        "en": "Remedial",
        "zh": "错题",
    },
    "notes.remedial_card_topic": {
        "en": "Missed Question {index}: {topic}",
        "zh": "答错题 {index}：{topic}",
    },
    "notes.remedial_source": {
        "en": "Quiz: {topic}",
        "zh": "测验：{topic}",
    },
    "notes.remedial_not_answered": {
        "en": "Not Answered",
        "zh": "未作答",
    },
    "notes.remedial_unknown": {
        "en": "Unknown",
        "zh": "未知",
    },
    "notes.remedial_review": {
        "en": "Review core concept from document.",
        "zh": "请回顾文档中的核心概念。",
    },
    "notes.remedial_question_default": {
        "en": "Question {index}",
        "zh": "第 {index} 题",
    },
    "notes.remedial_explanation": {
        "en": "Explanation: {explanation}",
        "zh": "解析：{explanation}",
    },
    "notes.remedial_question_line": {
        "en": "Question: {question}",
        "zh": "题目：{question}",
    },
    "notes.remedial_your_answer": {
        "en": "Your Answer: {answer}",
        "zh": "你的答案：{answer}",
    },
    "notes.remedial_correct_answer": {
        "en": "Correct Answer: {answer}",
        "zh": "正确答案：{answer}",
    },
    "notes.remedial_key_concept": {
        "en": "Key Concept: {concept}",
        "zh": "关键概念：{concept}",
    },
    "notes.remedial_perfect_title": {
        "en": "Perfect Score! ({topic})",
        "zh": "满分通过！（{topic}）",
    },
    "notes.remedial_perfect_summary": {
        "en": "Congratulations! You answered all questions correctly in your latest quiz.",
        "zh": "恭喜！你在最近一次测验中全部答对了。",
    },
    "notes.remedial_perfect_point_1": {
        "en": "Excellent mastery of concepts!",
        "zh": "对概念的掌握非常到位！",
    },
    "notes.remedial_perfect_point_2": {
        "en": "Keep reviewing core notes to retain knowledge.",
        "zh": "继续复习核心笔记，巩固记忆。",
    },
    "notes.remedial_pdf_subtitle": {
        "en": "Targeted Remedial Study Report for Missed Quiz Questions",
        "zh": "针对测验错题的专项复习报告",
    },
    "notes.remedial_default_topic": {
        "en": "Missed Concept",
        "zh": "错题概念",
    },
    # ── Quiz ─────────────────────────────────────────────────────────────────
    "quiz.no_documents": {
        "en": "No documents found in this knowledge space. Please upload documents first.",
        "zh": "该知识空间中没有文档，请先上传文档。",
    },
    "quiz.generation_failed": {
        "en": "Failed to generate valid quiz questions from the configured LLM. Please try again.",
        "zh": "大模型未能生成有效的测验题目，请重试。",
    },
    "quiz.not_found": {
        "en": "Quiz not found.",
        "zh": "测验不存在。",
    },
    # ── AI answers ───────────────────────────────────────────────────────────
    "ai.no_documents": {
        "en": (
            "📄 **No relevant documents found in this Knowledge Space.**\n\n"
            "Please upload a PDF or PPTX file to this space using the sidebar. "
            "Once uploaded, I will answer your questions strictly using the information in your documents."
        ),
        "zh": (
            "📄 **该知识空间中未找到相关文档。**\n\n"
            "请先通过侧边栏上传 PDF 或 PPTX 文件。上传完成后，我会严格依据文档内容回答你的问题。"
        ),
    },
    "ai.not_found": {
        "en": (
            "I cannot find sufficient information in your uploaded documents to answer this question. "
            "Please check your uploaded files or upload additional relevant material."
        ),
        "zh": "在你上传的文档中找不到足够的信息来回答这个问题，请检查已上传的文件或补充相关资料。",
    },
    "ai.error_config": {
        "en": (
            "⚠️ **LLM not configured**: the backend has no usable API credentials. "
            "Set `LLM_API_KEY` in `.env` (get one at {docs_url}) and restart the backend container."
        ),
        "zh": (
            "⚠️ **LLM 未配置**：后端没有拿到可用的大模型 API 凭证。"
            "请在 `.env` 中填写 `LLM_API_KEY`（可在 {docs_url} 获取），然后重启 backend 容器。"
        ),
    },
    "ai.error_request": {
        "en": "⚠️ **LLM request failed**: {message}\n\nCheck the provider status, network access, and your API key, then try again.",
        "zh": "⚠️ **大模型调用失败**：{message}\n\n请检查服务商状态、网络连通性和 API Key 后重试。",
    },
    # ── Study recommendations ────────────────────────────────────────────────
    "recommend.all_correct": {
        "en": (
            "🎉 **Great job!** You have answered all quiz questions correctly in **{title}**.\n\n"
            "Keep up the good work! Try taking another quiz or uploading more material to challenge yourself."
        ),
        "zh": (
            "🎉 **表现很棒！** 你在 **{title}** 的测验中全部答对了。\n\n"
            "继续保持！可以再测一次，或上传更多资料来挑战自己。"
        ),
    },
    # ── Settings dialog ──────────────────────────────────────────────────────
    "settings.unsupported_language": {
        "en": "Unsupported language. Available languages: {languages}.",
        "zh": "不支持该语言。可选语言：{languages}。",
    },
    "settings.unknown_provider": {
        "en": "Unknown LLM provider. Available providers: {providers}.",
        "zh": "未知的大模型服务商。可选：{providers}。",
    },
    "settings.invalid_base_url": {
        "en": "The API base URL must start with http:// or https://.",
        "zh": "API 地址必须以 http:// 或 https:// 开头。",
    },
    "settings.test_ok": {
        "en": "Connection successful — the model answered the test prompt.",
        "zh": "连接成功——模型已正常应答测试请求。",
    },
    "settings.test_failed": {
        "en": "Could not reach the model. Check the base URL ({base_url}), the model name ({model}) and the API key.",
        "zh": "无法连接模型。请检查地址（{base_url}）、模型名（{model}）与 API Key。",
    },
    "settings.api_key_required": {
        "en": "The API key cannot be empty.",
        "zh": "API Key 不能为空。",
    },
    "settings.api_key_not_found": {
        "en": "That saved API key no longer exists.",
        "zh": "该 API Key 不存在。",
    },
    # ── Generated titles ─────────────────────────────────────────────────────
    "title.new_chat": {
        "en": "New Chat",
        "zh": "新建对话",
    },
    "title.new_space": {
        "en": "New Knowledge Space",
        "zh": "新建知识空间",
    },
}


def t(key: str, /, **params: object) -> str:
    """Translate ``key`` for the current language, falling back to English."""
    entry = MESSAGES.get(key)
    if entry is None:
        return key
    language = current_language()
    template = entry.get(language) or entry.get(DEFAULT_LANGUAGE) or key
    if not params:
        return template
    try:
        return template.format(**params)
    except (KeyError, IndexError, ValueError):
        return template


def t_in(language: str | None, key: str, /, **params: object) -> str:
    """Translate ``key`` for an explicit language instead of the current context."""
    entry = MESSAGES.get(key)
    if entry is None:
        return key
    code = normalize_language(language) or current_language()
    template = entry.get(code) or entry.get(DEFAULT_LANGUAGE) or key
    if not params:
        return template
    try:
        return template.format(**params)
    except (KeyError, IndexError, ValueError):
        return template


# ─── LLM language directive ──────────────────────────────────────────────────

_LANGUAGE_DIRECTIVES: Final[dict[str, str]] = {
    "en": "",
    "zh": (
        "LANGUAGE: Write every human-readable part of your output in Simplified Chinese (简体中文). "
        "This covers answers, questions, answer options, explanations, titles, summaries and bullet points. "
        "Keep any JSON keys, field names, numeric values and source filenames exactly as specified; "
        "translate only the values."
    ),
}


def language_directive(language: str | None = None) -> str:
    """Return the prompt fragment that forces the model to answer in the active language."""
    code = normalize_language(language) or current_language()
    return _LANGUAGE_DIRECTIVES.get(code, "")


def prompt_language_directive(language: str | None = None) -> str:
    """Language requirement formatted for insertion into a prompt (leading blank line)."""
    directive = language_directive(language)
    return f"\n\n{directive}" if directive else ""


def default_chat_titles() -> set[str]:
    """All placeholder chat titles, in every language (used to detect un-renamed chats)."""
    return {entry[DEFAULT_LANGUAGE] for entry in (
        MESSAGES["title.new_chat"], MESSAGES["title.new_space"],
    )} | {entry["zh"] for entry in (
        MESSAGES["title.new_chat"], MESSAGES["title.new_space"],
    )}


def remedial_title_prefixes() -> tuple[str, ...]:
    """Language-independent prefixes used to recognise remedial-note rows."""
    entry = MESSAGES["notes.remedial_title"]
    return tuple(
        template.split("{topic}", 1)[0].strip()
        for template in (entry["en"], entry["zh"])
    )
