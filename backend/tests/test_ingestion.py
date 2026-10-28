"""
Document ingestion tests: file type validation.
Tests that the /chats/{chat_id}/documents endpoint correctly:
  - Accepts PDF, PPTX, DOCX/DOC, MD, TXT, CSV/TSV
  - Rejects PNG with 422 and a helpful error message
"""
import io
import pytest
from httpx import AsyncClient
from unittest.mock import patch, AsyncMock


@pytest.fixture
def fake_file_content():
    return b"fake file content for testing"


async def _upload(client: AsyncClient, auth_headers: dict, filename: str,
                  content_type: str, content: bytes, title: str):
    """Create a chat, then upload one file with ingestion stubbed out."""
    chat_resp = await client.post("/chats", json={"title": title}, headers=auth_headers)
    assert chat_resp.status_code == 201
    chat_id = chat_resp.json()["id"]

    with patch("app.routers.documents._background_ingest", new_callable=AsyncMock):
        return await client.post(
            f"/chats/{chat_id}/documents",
            headers=auth_headers,
            files={"file": (filename, io.BytesIO(content), content_type)},
        )


@pytest.mark.asyncio
async def test_upload_docx_accepted(client: AsyncClient, auth_headers: dict, fake_file_content: bytes):
    """DOCX files must be accepted (returns 202 Accepted)."""
    response = await _upload(
        client, auth_headers,
        "document.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        fake_file_content, "DOCX Chat",
    )
    assert response.status_code == 202
    # The API stores the extension without the leading dot (documents.py:164).
    assert response.json()["file_type"] == "docx"


@pytest.mark.asyncio
async def test_upload_legacy_doc_accepted(client: AsyncClient, auth_headers: dict, fake_file_content: bytes):
    """Legacy binary .doc files must be accepted now that doc_legacy.py parses them."""
    response = await _upload(
        client, auth_headers, "report.doc", "application/msword",
        fake_file_content, "DOC Chat",
    )
    assert response.status_code == 202
    assert response.json()["file_type"] == "doc"


@pytest.mark.asyncio
async def test_upload_markdown_accepted(client: AsyncClient, auth_headers: dict, fake_file_content: bytes):
    """Markdown files must be accepted (returns 202 Accepted)."""
    response = await _upload(
        client, auth_headers, "notes.md", "text/markdown",
        fake_file_content, "MD Chat",
    )
    assert response.status_code == 202
    assert response.json()["file_type"] == "md"


@pytest.mark.asyncio
async def test_upload_txt_accepted(client: AsyncClient, auth_headers: dict, fake_file_content: bytes):
    """Plain text files must be accepted."""
    response = await _upload(
        client, auth_headers, "notes.txt", "text/plain",
        fake_file_content, "TXT Chat",
    )
    assert response.status_code == 202
    assert response.json()["file_type"] == "txt"


@pytest.mark.asyncio
async def test_upload_csv_accepted(client: AsyncClient, auth_headers: dict, fake_file_content: bytes):
    """CSV files must be accepted."""
    response = await _upload(
        client, auth_headers, "scores.csv", "text/csv",
        fake_file_content, "CSV Chat",
    )
    assert response.status_code == 202
    assert response.json()["file_type"] == "csv"


@pytest.mark.asyncio
async def test_upload_image_rejected(client: AsyncClient, auth_headers: dict, fake_file_content: bytes):
    """Image files must be rejected with 422."""
    chat_resp = await client.post("/chats", json={"title": "Chat 2"}, headers=auth_headers)
    chat_id = chat_resp.json()["id"]

    response = await client.post(
        f"/chats/{chat_id}/documents",
        headers=auth_headers,
        files={"file": ("photo.png", io.BytesIO(fake_file_content), "image/png")},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_upload_pdf_accepted(client: AsyncClient, auth_headers: dict, fake_file_content: bytes):
    """PDF files must be accepted (returns 202 Accepted)."""
    chat_resp = await client.post("/chats", json={"title": "PDF Chat"}, headers=auth_headers)
    chat_id = chat_resp.json()["id"]

    # Patch background ingestion so it doesn't actually run
    with patch("app.routers.documents._background_ingest", new_callable=AsyncMock):
        response = await client.post(
            f"/chats/{chat_id}/documents",
            headers=auth_headers,
            files={"file": ("lecture.pdf", io.BytesIO(fake_file_content), "application/pdf")},
        )
    assert response.status_code == 202
    data = response.json()
    assert data["filename"] == "lecture.pdf"
    assert data["status"] == "processing"


@pytest.mark.asyncio
async def test_upload_pptx_accepted(client: AsyncClient, auth_headers: dict, fake_file_content: bytes):
    """PPTX files must be accepted."""
    chat_resp = await client.post("/chats", json={"title": "PPTX Chat"}, headers=auth_headers)
    chat_id = chat_resp.json()["id"]

    with patch("app.routers.documents._background_ingest", new_callable=AsyncMock):
        response = await client.post(
            f"/chats/{chat_id}/documents",
            headers=auth_headers,
            files={"file": ("slides.pptx", io.BytesIO(fake_file_content), "application/vnd.openxmlformats-officedocument.presentationml.presentation")},
        )
    assert response.status_code == 202
    assert response.json()["file_type"] == "pptx"


@pytest.mark.asyncio
async def test_upload_requires_auth(client: AsyncClient, fake_file_content: bytes):
    """Upload endpoint must require authentication."""
    response = await client.post(
        "/chats/fake-chat-id/documents",
        files={"file": ("doc.pdf", io.BytesIO(fake_file_content), "application/pdf")},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_chunker_basic():
    """Unit test for chunker — verifies basic chunking output."""
    from app.utils.chunker import chunk_pages

    pages = [
        {
            "text": "The quick brown fox jumps over the lazy dog. " * 20,
            "page": 1,
            "source": "test.pdf",
        }
    ]
    chunks = chunk_pages(pages, chunk_size=50, overlap=10)
    assert len(chunks) > 0
    for chunk in chunks:
        assert "text" in chunk
        assert "page" in chunk
        assert "chunk_index" in chunk
        assert chunk["token_count"] > 0
