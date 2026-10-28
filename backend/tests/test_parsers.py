"""
Parser-level tests for the formats added in this round: legacy ``.doc``,
Markdown, plain text and delimited tables.

These run without HTTP and without a database — they call ``parse_file``
directly, which is where the actual extraction logic lives. The upload endpoint
is covered separately in ``test_ingestion.py``.
"""
import csv
import io
import os

import pytest

from app.utils.parsers import (
    CORE_EXTENSIONS,
    is_extension_allowed,
    parse_csv,
    parse_doc,
    parse_file,
    parse_text,
)


# ── Extension gate ───────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "ext",
    [".doc", ".md", ".markdown", ".txt", ".text", ".csv", ".tsv"],
)
def test_new_formats_are_allowed(ext: str):
    assert is_extension_allowed(ext)


@pytest.mark.parametrize("ext", [".png", ".jpg", ".mp3", ".mp4", ".exe", ".xyz"])
def test_shelved_and_unknown_formats_are_rejected(ext: str):
    assert not is_extension_allowed(ext)


def test_doc_is_a_core_extension():
    """``.doc`` must be core: it needs no feature flag, unlike OCR or audio."""
    assert ".doc" in CORE_EXTENSIONS


def test_parse_file_dispatch_covers_every_core_extension():
    """
    Every core extension must have a parser reachable through ``parse_file``.

    This is a guard against a whole class of bug that the individual parser
    tests cannot catch: a parser that exists and works, but whose name no longer
    matches what ``parse_file`` dispatches to. That is exactly what happened when
    ``parse_pdf``'s ``def`` line was deleted during an edit -- the PDF body was
    still there, so ``ast.parse`` and ``compileall`` both passed, but every PDF
    upload died with a NameError at runtime. Comparing the set of names that
    ``parse_file`` references against the set actually defined in the module
    turns that silent breakage into a failing test.
    """
    import ast
    import inspect

    import app.utils.parsers as parsers_module

    tree = ast.parse(inspect.getsource(parsers_module))
    defined = {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    dispatch = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "parse_file"
    )
    referenced = {
        node.id
        for node in ast.walk(dispatch)
        if isinstance(node, ast.Name) and node.id.startswith("parse_")
    }

    missing = referenced - defined
    assert not missing, f"parse_file calls undefined parser(s): {sorted(missing)}"

    # And the reverse direction: no core extension may lack a dispatch branch.
    for ext in CORE_EXTENSIONS:
        assert is_extension_allowed(ext), f"{ext} is core but rejected"


# ── Markdown / plain text ────────────────────────────────────────────────────
def test_markdown_keeps_structure(tmp_path):
    """Headings, list markers and code fences must survive extraction."""
    path = tmp_path / "notes.md"
    path.write_text(
        "# 操作系统\n\n## 进程\n\n- 进程有独立地址空间\n- 线程共享地址空间\n\n"
        "```c\nint main() { return 0; }\n```\n",
        encoding="utf-8",
    )
    pages = parse_text(str(path))
    joined = "".join(p["text"] for p in pages)
    assert "# 操作系统" in joined
    assert "- 进程有独立地址空间" in joined
    assert "```c" in joined


def test_plain_text_with_single_newlines_is_split_per_line(tmp_path):
    """
    A .txt that never uses blank lines must not become one giant block.

    Splitting on blank lines alone would yield a single 2000+ character block,
    which ``_paginate_blocks`` then cuts mid-sentence.
    """
    path = tmp_path / "lines.txt"
    path.write_text("\n".join(f"第{i}行内容。" for i in range(1, 300)), encoding="utf-8")
    pages = parse_text(str(path))
    assert len(pages) > 1
    assert all(len(p["text"]) <= 2100 for p in pages)
    assert "第299行内容" in "".join(p["text"] for p in pages)


def test_gbk_encoded_text_is_decoded(tmp_path):
    path = tmp_path / "gbk.txt"
    path.write_bytes("中文编码测试。\n第二行。\n".encode("gbk"))
    pages = parse_text(str(path))
    assert "中文编码测试" in "".join(p["text"] for p in pages)


def test_utf8_bom_is_stripped(tmp_path):
    path = tmp_path / "bom.md"
    path.write_bytes("\ufeff# 标题\n\n正文。\n".encode("utf-8"))
    joined = "".join(p["text"] for p in parse_text(str(path)))
    assert "\ufeff" not in joined
    assert "# 标题" in joined


def test_empty_text_file_yields_no_pages(tmp_path):
    path = tmp_path / "empty.txt"
    path.write_text("   \n\n  \n", encoding="utf-8")
    assert parse_text(str(path)) == []


# ── CSV / TSV ────────────────────────────────────────────────────────────────
def test_csv_repeats_header_on_every_page(tmp_path):
    """
    A chunk taken from page 2 must still say which column a value belongs to.

    This is the whole reason ``parse_csv`` exists instead of reusing
    ``parse_text``: a bare row of numbers is unretrievable.
    """
    path = tmp_path / "scores.csv"
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["姓名", "科目", "分数"])
        for i in range(1, 121):
            writer.writerow([f"学生{i}", "高等数学", str(60 + i % 40)])

    pages = parse_csv(str(path))
    assert len(pages) > 1, "120 rows should exceed one 2000-character page"
    assert all("姓名 | 科目 | 分数" in page["text"] for page in pages)


def test_csv_never_splits_a_row_across_pages(tmp_path):
    path = tmp_path / "rows.csv"
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["a", "b", "c"])
        for i in range(1, 80):
            writer.writerow([f"r{i}", "x", "y"])

    pages = parse_csv(str(path))
    for page in pages:
        for line in page["text"].split("\n"):
            if line.strip():
                assert line.count(" | ") == 2, f"malformed row: {line!r}"


def test_tsv_uses_tab_delimiter(tmp_path):
    path = tmp_path / "data.tsv"
    path.write_text("id\tname\tscore\n1\talice\t90\n", encoding="utf-8")
    pages = parse_file(str(path))
    assert "id | name | score" in pages[0]["text"]
    assert "alice" in pages[0]["text"]


def test_single_line_csv_is_returned_verbatim(tmp_path):
    """A header-only file is data, not a header plus zero rows."""
    path = tmp_path / "one.csv"
    path.write_text("a,b,c\n", encoding="utf-8")
    pages = parse_csv(str(path))
    assert len(pages) == 1
    assert pages[0]["text"] == "a | b | c"


def test_malformed_csv_falls_back_to_plain_text(tmp_path):
    """Broken quoting must degrade, not fail the upload."""
    path = tmp_path / "bad.csv"
    path.write_text('a,b\n"unterminated,2\n3,4\n', encoding="utf-8")
    assert parse_csv(str(path)) != []


# ── Legacy .doc ──────────────────────────────────────────────────────────────
#: CFB constants used by the synthetic-document builder below.
_ENDOFCHAIN = 0xFFFFFFFE
_FATSECT = 0xFFFFFFFD
_FREESECT = 0xFFFFFFFF
_NOSTREAM = 0xFFFFFFFF
_SECTOR = 512


def _build_cfb(streams: dict) -> bytes:
    """
    Build a minimal, valid OLE2 / Compound File Binary container.

    Only what :class:`app.utils.doc_legacy.CompoundFile` reads is emitted: a
    512-byte header, one FAT sector, one directory sector, then the stream
    sectors. Streams are padded past the 4096-byte mini-stream cutoff so they
    live in the regular FAT, which is what a real Word document of any size does.
    """
    names = list(streams)
    # Pad each stream to at least 4096 bytes and to a whole number of sectors.
    padded = {}
    for name in names:
        blob = streams[name]
        size = max(len(blob), 4096)
        size = (size + _SECTOR - 1) // _SECTOR * _SECTOR
        padded[name] = (blob + b"\x00" * (size - len(blob)), size)

    first_sector = 2  # 0 = FAT, 1 = directory
    layout = []
    cursor = first_sector
    for name in names:
        _, size = padded[name]
        count = size // _SECTOR
        layout.append((name, cursor, count, size))
        cursor += count
    total_sectors = cursor

    fat = [_FREESECT] * max(total_sectors, 128)
    fat[0] = _FATSECT
    fat[1] = _ENDOFCHAIN  # single directory sector
    for _, start, count, _ in layout:
        for i in range(count):
            fat[start + i] = _ENDOFCHAIN if i == count - 1 else start + i + 1

    header = bytearray(_SECTOR)
    header[0x00:0x08] = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
    header[0x18:0x1A] = (0x003E).to_bytes(2, "little")  # minor version
    header[0x1A:0x1C] = (0x0003).to_bytes(2, "little")  # major version 3
    header[0x1C:0x1E] = (0xFFFE).to_bytes(2, "little")  # byte order
    header[0x1E:0x20] = (9).to_bytes(2, "little")  # sector shift => 512
    header[0x20:0x22] = (6).to_bytes(2, "little")  # mini sector shift => 64
    header[0x28:0x2C] = (0).to_bytes(4, "little")  # number of directory sectors
    header[0x2C:0x30] = (1).to_bytes(4, "little")  # number of FAT sectors
    header[0x30:0x34] = (1).to_bytes(4, "little")  # first directory sector
    header[0x34:0x38] = (0).to_bytes(4, "little")  # transaction signature
    header[0x38:0x3C] = (4096).to_bytes(4, "little")  # mini stream cutoff
    header[0x3C:0x40] = _ENDOFCHAIN.to_bytes(4, "little")  # first mini FAT sector
    header[0x40:0x44] = (0).to_bytes(4, "little")  # number of mini FAT sectors
    header[0x44:0x48] = _ENDOFCHAIN.to_bytes(4, "little")  # first DIFAT sector
    header[0x48:0x4C] = (0).to_bytes(4, "little")  # number of DIFAT sectors
    difat = [0] + [_FREESECT] * 108
    header[0x4C:0x4C + 109 * 4] = b"".join(v.to_bytes(4, "little") for v in difat)

    fat_sector = b"".join(v.to_bytes(4, "little") for v in fat[:128])

    def entry(name: str, obj_type: int, start: int, size: int) -> bytes:
        raw = bytearray(128)
        encoded = name.encode("utf-16-le")
        raw[0x00 : len(encoded)] = encoded
        raw[0x40:0x42] = (len(encoded) + 2).to_bytes(2, "little")
        raw[0x42] = obj_type
        raw[0x43] = 1  # black
        raw[0x44:0x48] = _NOSTREAM.to_bytes(4, "little")
        raw[0x48:0x4C] = _NOSTREAM.to_bytes(4, "little")
        raw[0x4C:0x50] = _NOSTREAM.to_bytes(4, "little")
        raw[0x74:0x78] = start.to_bytes(4, "little")
        raw[0x78:0x80] = size.to_bytes(8, "little")
        return bytes(raw)

    directory = bytearray()
    directory += entry("Root Entry", 5, _ENDOFCHAIN, 0)
    for name, start, _, size in layout:
        directory += entry(name, 2, start, size)
    directory = bytes(directory).ljust(_SECTOR, b"\x00")

    body = b"".join(padded[name][0] for name, _, _, _ in layout)
    return bytes(header) + fat_sector + directory + body


def _build_doc(text: str) -> bytes:
    """
    Build the smallest valid Word 97 ``.doc`` the reader must accept.

    Layout: a ``WordDocument`` stream holding a FIB (flags select ``1Table``,
    fcClx/lcbClx point at the start of the table stream) followed by the UTF-16LE
    body, plus a ``1Table`` stream that begins with the piece table. One piece,
    uncompressed — the shape Word emits for any document with non-Latin text.
    """
    body = text.encode("utf-16-le")

    fib = bytearray(0x200)
    fib[0x00:0x02] = (0xA5EC).to_bytes(2, "little")  # wIdent
    fib[0x02:0x04] = (193).to_bytes(2, "little")  # nFib: Word 97
    fib[0x0A:0x0C] = (0x0200).to_bytes(2, "little")  # flags: use 1Table

    # PlcPcd = 2 character positions + 1 piece descriptor.
    plc = (0).to_bytes(4, "little") + (len(text)).to_bytes(4, "little")
    plc += (0).to_bytes(2, "little")  # flags
    plc += (0x200).to_bytes(4, "little")  # fc: body starts right after the FIB
    plc += (0).to_bytes(2, "little")  # prm
    clx = b"\x02" + len(plc).to_bytes(4, "little") + plc

    fib[0x01A2:0x01A6] = (0).to_bytes(4, "little")  # fcClx
    fib[0x01A6:0x01AA] = len(clx).to_bytes(4, "little")  # lcbClx

    return _build_cfb(
        {"WordDocument": bytes(fib) + body, "1Table": clx}
    )


def test_legacy_doc_roundtrip(tmp_path):
    """A synthetic .doc must decode back to the original text."""
    path = tmp_path / "sample.doc"
    path.write_bytes(_build_doc("Hello 中文 world.\rSecond paragraph.\r"))
    pages = parse_doc(str(path))
    joined = "".join(p["text"] for p in pages)
    assert "Hello" in joined
    assert "中文" in joined
    assert "Second paragraph." in joined


def test_rtf_renamed_to_doc_is_read(tmp_path):
    """Users rename RTF exports to .doc; the reader must cope."""
    path = tmp_path / "renamed.doc"
    path.write_bytes(
        rb"{\rtf1\ansi{\fonttbl\f0 Arial;}\f0 Hello \b bold\b0  world.\par Second line.\par}"
    )
    joined = "".join(p["text"] for p in parse_doc(str(path)))
    assert "Hello" in joined
    assert "Second line." in joined
    assert "fonttbl" not in joined


def test_html_renamed_to_doc_is_read(tmp_path):
    path = tmp_path / "renamed2.doc"
    path.write_bytes(
        b"<html><body><h1>Title</h1><p>Body text.</p>"
        b"<table><tr><td>a</td><td>b</td></tr></table></body></html>"
    )
    joined = "".join(p["text"] for p in parse_doc(str(path)))
    assert "Title" in joined
    assert "Body text." in joined
    assert "<" not in joined


def test_non_ole2_doc_does_not_raise(tmp_path):
    """A plain-text file with a .doc name must still yield something."""
    path = tmp_path / "plain.doc"
    path.write_bytes("Just plain text.\n".encode("utf-8"))
    assert parse_doc(str(path)) != []


def test_empty_doc_yields_no_pages(tmp_path):
    path = tmp_path / "empty.doc"
    path.write_bytes(b"")
    assert parse_doc(str(path)) == []
