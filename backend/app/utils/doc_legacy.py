"""
Pure-Python reader for legacy Word ``.doc`` files (Word 97-2003).

A ``.doc`` is an OLE2 / Compound File Binary container holding a ``WordDocument``
stream plus a ``0Table``/``1Table`` stream. The body text is not stored
contiguously: it lives in *pieces* described by a piece table (``CLX``/``PlcPcd``)
inside the table stream, where each piece is either CP1252 (one byte per
character) or UTF-16LE (two bytes per character).

Why a hand-written reader instead of a dependency
-------------------------------------------------
The project ships fully offline as a single PyInstaller bundle. ``python-docx``
cannot open this format at all, ``olefile`` is not installed, and COM automation
would require a licensed Word install on the target machine. The CFB format and
the Word piece table are both stable, documented and small enough to implement
here, so ``.doc`` support costs nothing at install time.

Robustness
----------
Real-world ``.doc`` files are frequently mislabelled: Word users rename ``.rtf``
or ``.html`` exports to ``.doc``, and Word itself can emit a plain-text file with
a ``.doc`` extension. :func:`extract_doc_text` sniffs the container before
parsing and falls back to the piece table, then to a byte-level heuristic scan,
so a slightly damaged file still yields searchable text instead of failing the
upload.
"""
from __future__ import annotations

import logging
import re
import struct
from typing import List

logger = logging.getLogger(__name__)

# ── Compound File Binary constants ───────────────────────────────────────────
_CFB_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_ENDOFCHAIN = 0xFFFFFFFE
_FREESECT = 0xFFFFFFFF
_MAXREGSECT = 0xFFFFFFFA
_NOSTREAM = 0xFFFFFFFF

_HEADER_SIZE = 512
_DIR_ENTRY_SIZE = 128

#: Directory entry object types.
_TYPE_STORAGE = 1
_TYPE_STREAM = 2
_TYPE_ROOT = 5

#: Word FIB: bit in the flags word that selects the ``1Table`` stream.
_FIB_FLAGS_OFFSET = 0x000A
_FIB_WHICH_TABLE = 0x0200
#: Word 97+ (nFib >= 101) piece-table location inside the FIB.
_FIB_FCCLX_OFFSET = 0x01A2

#: Control characters that Word stores inline and that carry meaning.
_CHAR_MAP = {
    "\r": "\n",  # paragraph mark
    "\x07": " | ",  # end of table cell / row
    "\x0b": "\n",  # manual line break
    "\x0c": "\n",  # page / section break
    "\x1e": "-",  # non-breaking hyphen
    "\x1f": "",  # optional hyphen
    "\x13": "",  # field begin
    "\x14": " ",  # field separator
    "\x15": "",  # field end
    "\x08": "",  # drawn object anchor
    "\x01": "",  # embedded picture
    "\x02": "",  # footnote reference
}

#: Everything else in the C0/C1 range is noise for retrieval purposes.
_STRIP_RE = re.compile(r"[\x00-\x08\x0e-\x12\x16-\x1d]")


class DocParseError(Exception):
    """Raised when a ``.doc`` file cannot be read at all."""


# ─────────────────────────────────────────────────────────────────────────────
# Compound File Binary (OLE2) reader
# ─────────────────────────────────────────────────────────────────────────────
class _DirEntry:
    __slots__ = ("name", "obj_type", "start", "size")

    def __init__(self, name: str, obj_type: int, start: int, size: int) -> None:
        self.name = name
        self.obj_type = obj_type
        self.start = start
        self.size = size


class CompoundFile:
    """
    Minimal read-only CFB parser: FAT, DIFAT, mini-FAT and the directory tree.

    Only the pieces RagVault needs are implemented — opening a container, listing
    its streams and reading one stream's bytes by name.
    """

    def __init__(self, data: bytes) -> None:
        if len(data) < _HEADER_SIZE or not data.startswith(_CFB_MAGIC):
            raise DocParseError("not an OLE2 compound file")

        self._data = data
        sector_shift = struct.unpack_from("<H", data, 0x1E)[0]
        mini_shift = struct.unpack_from("<H", data, 0x20)[0]
        if sector_shift not in (9, 12):
            raise DocParseError(f"unsupported CFB sector shift: {sector_shift}")
        if mini_shift != 6:
            raise DocParseError(f"unsupported CFB mini sector shift: {mini_shift}")

        self.sector_size = 1 << sector_shift
        self.mini_sector_size = 1 << mini_shift

        num_fat = struct.unpack_from("<I", data, 0x2C)[0]
        self._dir_start = struct.unpack_from("<I", data, 0x30)[0]
        self._mini_cutoff = struct.unpack_from("<I", data, 0x38)[0]
        mini_fat_start = struct.unpack_from("<I", data, 0x3C)[0]
        num_mini_fat = struct.unpack_from("<I", data, 0x40)[0]
        difat_start = struct.unpack_from("<I", data, 0x44)[0]
        num_difat = struct.unpack_from("<I", data, 0x48)[0]

        self._fat = self._load_fat(num_fat, difat_start, num_difat)
        self._mini_fat = self._load_mini_fat(mini_fat_start, num_mini_fat)
        self._entries = self._load_directory()

        root = self._entries[0]
        self._mini_stream = (
            self._read_chain(root.start, root.size, use_mini=False) if root.size else b""
        )

    # -- primitives ----------------------------------------------------------
    def _sector(self, index: int) -> bytes:
        """Return the raw bytes of regular sector ``index``."""
        if index > _MAXREGSECT:
            raise DocParseError(f"sector index out of range: {index}")
        start = _HEADER_SIZE + index * self.sector_size
        end = start + self.sector_size
        if start >= len(self._data):
            raise DocParseError(f"sector {index} lies past end of file")
        # A truncated final sector is padded rather than treated as fatal.
        return self._data[start:end].ljust(self.sector_size, b"\x00")

    def _chain(self, start: int, table: List[int], limit: int) -> List[int]:
        """Follow a FAT/mini-FAT chain, guarding against cycles and overruns."""
        chain: List[int] = []
        seen: set[int] = set()
        sect = start
        while sect <= _MAXREGSECT and len(chain) < limit:
            if sect in seen:
                logger.debug("CFB chain loops at sector %d; stopping", sect)
                break
            seen.add(sect)
            chain.append(sect)
            if sect >= len(table):
                break
            sect = table[sect]
        return chain

    def _read_chain(self, start: int, size: int, use_mini: bool) -> bytes:
        if size <= 0:
            return b""
        if use_mini:
            table, blob, unit = self._mini_fat, self._mini_stream, self.mini_sector_size
        else:
            table, blob, unit = self._fat, None, self.sector_size

        need = (size + unit - 1) // unit
        chain = self._chain(start, table, need + 8)

        out = bytearray()
        for sect in chain:
            if use_mini:
                offset = sect * unit
                out += blob[offset : offset + unit]
            else:
                out += self._sector(sect)
            if len(out) >= size:
                break
        return bytes(out[:size])

    # -- structure loading ---------------------------------------------------
    def _load_fat(self, num_fat: int, difat_start: int, num_difat: int) -> List[int]:
        per_sector = self.sector_size // 4
        difat = list(struct.unpack_from("<109I", self._data, 0x4C))

        sect = difat_start
        guard = 0
        while sect <= _MAXREGSECT and guard < num_difat + 8:
            block = self._sector(sect)
            values = list(struct.unpack_from(f"<{per_sector}I", block, 0))
            difat.extend(values[:-1])  # last entry chains to the next DIFAT sector
            sect = values[-1]
            guard += 1

        fat: List[int] = []
        for fat_sect in [s for s in difat if s <= _MAXREGSECT][:num_fat]:
            block = self._sector(fat_sect)
            fat.extend(struct.unpack_from(f"<{per_sector}I", block, 0))
        if not fat:
            raise DocParseError("compound file has an empty FAT")
        return fat

    def _load_mini_fat(self, start: int, num_mini_fat: int) -> List[int]:
        per_sector = self.sector_size // 4
        mini_fat: List[int] = []
        sect = start
        guard = 0
        while sect <= _MAXREGSECT and guard < num_mini_fat + 8:
            block = self._sector(sect)
            mini_fat.extend(struct.unpack_from(f"<{per_sector}I", block, 0))
            if sect >= len(self._fat):
                break
            sect = self._fat[sect]
            guard += 1
        return mini_fat

    def _load_directory(self) -> List[_DirEntry]:
        raw = self._read_chain(
            self._dir_start,
            # The directory has no declared length; the chain limit is the file
            # size, which is always an upper bound on the number of sectors.
            len(self._data),
            use_mini=False,
        )
        entries: List[_DirEntry] = []
        for offset in range(0, len(raw) - _DIR_ENTRY_SIZE + 1, _DIR_ENTRY_SIZE):
            chunk = raw[offset : offset + _DIR_ENTRY_SIZE]
            name_len = struct.unpack_from("<H", chunk, 0x40)[0]
            obj_type = chunk[0x42]
            if obj_type not in (_TYPE_STORAGE, _TYPE_STREAM, _TYPE_ROOT):
                entries.append(_DirEntry("", obj_type, 0, 0))
                continue
            # name_len counts the terminating NUL in bytes.
            chars = max(0, min(name_len, 64) // 2 - 1)
            name = chunk[: chars * 2].decode("utf-16-le", errors="replace")
            start = struct.unpack_from("<I", chunk, 0x74)[0]
            size = struct.unpack_from("<Q", chunk, 0x78)[0]
            entries.append(_DirEntry(name, obj_type, start, size))
        if not entries:
            raise DocParseError("compound file has an empty directory")
        return entries

    # -- public API ----------------------------------------------------------
    def stream_names(self) -> List[str]:
        return [e.name for e in self._entries if e.obj_type == _TYPE_STREAM]

    def read_stream(self, name: str) -> bytes:
        """Return the full contents of stream ``name`` (case-insensitive)."""
        target = name.lower()
        for entry in self._entries:
            if entry.obj_type == _TYPE_STREAM and entry.name.lower() == target:
                # Streams smaller than the cutoff live in the mini stream.
                use_mini = entry.size < self._mini_cutoff
                return self._read_chain(entry.start, entry.size, use_mini=use_mini)
        raise DocParseError(f"stream not found: {name}")


# ─────────────────────────────────────────────────────────────────────────────
# Word text extraction
# ─────────────────────────────────────────────────────────────────────────────
def _clean(raw: str) -> str:
    """Map Word's inline control characters to readable text."""
    for src, dst in _CHAR_MAP.items():
        if src in raw:
            raw = raw.replace(src, dst)
    raw = _STRIP_RE.sub("", raw)
    # Collapse the blank lines Word leaves around table cells and paragraphs.
    raw = re.sub(r"\n{3,}", "\n\n", raw)
    return raw.strip()


def _piece_table_text(word_stream: bytes, table: bytes, fc_clx: int, lcb_clx: int) -> str:
    """
    Decode the document body using the piece table (CLX) in the table stream.

    The CLX is a short sequence of Prc structures (0x01, formatting exceptions we
    can ignore) followed by one Pcdt (0x02) that holds the PlcPcd: an array of
    character-position boundaries plus one 8-byte piece descriptor each.
    """
    clx = table[fc_clx : fc_clx + lcb_clx]
    if not clx:
        return ""

    plc = b""
    pos = 0
    while pos < len(clx):
        kind = clx[pos]
        if kind == 0x01:  # Prc: 2-byte length, then that many bytes of grpprl
            if pos + 3 > len(clx):
                break
            cb = struct.unpack_from("<h", clx, pos + 1)[0]
            if cb < 0:
                break
            pos += 3 + cb
        elif kind == 0x02:  # Pcdt: 4-byte length, then the PlcPcd itself
            if pos + 5 > len(clx):
                break
            lcb = struct.unpack_from("<I", clx, pos + 1)[0]
            plc = clx[pos + 5 : pos + 5 + lcb]
            break
        else:
            break

    if len(plc) < 16:
        return ""

    # lcb = 4*(n+1) character positions + 8*n piece descriptors.
    n_pieces = (len(plc) - 4) // 12
    if n_pieces <= 0:
        return ""

    cps = struct.unpack_from(f"<{n_pieces + 1}I", plc, 0)
    pieces: List[str] = []

    for i in range(n_pieces):
        cp_start, cp_end = cps[i], cps[i + 1]
        count = cp_end - cp_start
        if count <= 0:
            continue
        # Piece descriptor: 2 bytes flags, 4 bytes fc, 2 bytes prm.
        fc_raw = struct.unpack_from("<I", plc, 4 * (n_pieces + 1) + 8 * i + 2)[0]
        compressed = bool(fc_raw & 0x40000000)
        fc = fc_raw & 0x3FFFFFFF
        if compressed:
            # Bit 30 set: 8-bit CP1252 text, and fc counts in bytes / 2.
            fc //= 2
            pieces.append(word_stream[fc : fc + count].decode("cp1252", errors="replace"))
        else:
            pieces.append(
                word_stream[fc : fc + count * 2].decode("utf-16-le", errors="replace")
            )

    return "".join(pieces)


def _heuristic_text(word_stream: bytes) -> str:
    """
    Last-resort scan for a damaged or non-standard piece table.

    Word 97+ stores text as UTF-16LE, so alternating ASCII/zero bytes are a strong
    signal. This loses exact ordering around fields and tables but keeps the
    document searchable.
    """
    found = re.findall(rb"(?:[\x20-\x7e]\x00){8,}", word_stream)
    runs: List[str] = []
    for match in found:
        try:
            text = match.decode("utf-16-le", errors="ignore").strip()
        except Exception:
            continue
        if text and not text.startswith("Microsoft"):
            runs.append(text)
    return "\n".join(runs)


def _looks_like_rtf(data: bytes) -> bool:
    return data.lstrip()[:5].lower() == b"{\\rtf"


def _looks_like_html(data: bytes) -> bool:
    head = data.lstrip()[:512].lower()
    return head.startswith(b"<html") or b"<html" in head[:200] or head.startswith(b"<!doctype")


def _strip_rtf(data: bytes) -> str:
    """Extract visible text from an RTF document saved with a ``.doc`` name."""
    text = data.decode("latin-1", errors="replace")
    # Drop destination groups we do not want, then control words.
    text = re.sub(r"\{\\\*?\\(?:fonttbl|colortbl|stylesheet|info|pict)[^{}]*\}", "", text)
    text = re.sub(r"\\'([0-9a-fA-F]{2})", lambda m: chr(int(m.group(1), 16)), text)
    text = re.sub(r"\\u(-?\d+)\??", lambda m: chr(int(m.group(1)) % 65536), text)
    # Convert breaks BEFORE stripping control words: the generic regex below
    # also matches \par/\line, so converting afterwards never fires.
    text = text.replace("\\par", "\n").replace("\\line", "\n")
    text = re.sub(r"\\[a-zA-Z]+-?\d* ?", "", text)
    text = re.sub(r"[{}]", "", text)
    return _clean(text)


def _strip_html(data: bytes) -> str:
    """Extract visible text from an HTML document saved with a ``.doc`` name."""
    text = data.decode("utf-8", errors="replace")
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", "", text)
    text = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</h[1-6]>", "\n", text)
    text = re.sub(r"(?i)</td>|</th>", " | ", text)
    text = re.sub(r"<[^>]+>", "", text)
    import html as _html

    return _clean(_html.unescape(text))


def extract_doc_text(path: str) -> str:
    """
    Return the full text of a legacy ``.doc`` file.

    Handles three shapes found in the wild: a real OLE2 container (normal case),
    and RTF or HTML content that was renamed to ``.doc``.
    """
    with open(path, "rb") as handle:
        data = handle.read()
    if not data:
        return ""

    if _looks_like_rtf(data):
        logger.info("[DOC] %s is RTF content with a .doc extension", path)
        return _strip_rtf(data)
    if _looks_like_html(data):
        logger.info("[DOC] %s is HTML content with a .doc extension", path)
        return _strip_html(data)

    if not data.startswith(_CFB_MAGIC):
        # Not a compound file: some tools write plain text with a .doc name.
        logger.warning("[DOC] %s is not an OLE2 file; treating as plain text", path)
        for encoding in ("utf-8-sig", "gb18030", "utf-16", "latin-1"):
            try:
                return _clean(data.decode(encoding))
            except (UnicodeDecodeError, UnicodeError):
                continue
        return _clean(data.decode("utf-8", errors="replace"))

    compound = CompoundFile(data)
    try:
        word_stream = compound.read_stream("WordDocument")
    except DocParseError:
        raise DocParseError("compound file has no WordDocument stream")

    if len(word_stream) < 0x200:
        raise DocParseError("WordDocument stream is truncated")

    flags = struct.unpack_from("<H", word_stream, _FIB_FLAGS_OFFSET)[0]
    table_name = "1Table" if flags & _FIB_WHICH_TABLE else "0Table"

    table = b""
    try:
        table = compound.read_stream(table_name)
    except DocParseError:
        # Some writers store the table under the other name; try it before
        # giving up on the structured path.
        alternate = "0Table" if table_name == "1Table" else "1Table"
        try:
            table = compound.read_stream(alternate)
            table_name = alternate
        except DocParseError:
            logger.warning("[DOC] No %s stream in %s; using heuristic scan", table_name, path)

    if table:
        fc_clx, lcb_clx = struct.unpack_from("<II", word_stream, _FIB_FCCLX_OFFSET)
        if 0 < lcb_clx and fc_clx + lcb_clx <= len(table):
            try:
                text = _piece_table_text(word_stream, table, fc_clx, lcb_clx)
            except (struct.error, IndexError) as exc:
                logger.warning("[DOC] Piece table unreadable in %s: %s", path, exc)
                text = ""
            cleaned = _clean(text)
            if cleaned:
                return cleaned
        else:
            logger.warning(
                "[DOC] Piece table offsets out of range in %s (fcClx=%d, lcbClx=%d, table=%d bytes)",
                path,
                fc_clx,
                lcb_clx,
                len(table),
            )

    logger.warning("[DOC] Falling back to heuristic scan for %s", path)
    return _clean(_heuristic_text(word_stream))


def doc_to_blocks(path: str) -> List[str]:
    """Split a ``.doc`` file into paragraph-level blocks for the chunker."""
    text = extract_doc_text(path)
    if not text.strip():
        return []
    blocks: List[str] = []
    for raw in text.split("\n"):
        line = raw.strip()
        if line:
            blocks.append(line)
    return blocks
