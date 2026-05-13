"""Markdown 感知的递归文本分块器，对齐官方 text-chunker.ts

特性：
1. 每个 chunk 带 headingPath 面包屑
2. 分裂优先级：heading > 段落 > 换行 > 句子 > 空格 > 硬切
3. 不拆分代码块和表格
4. 去除 YAML frontmatter
5. 相邻 chunk 之间有 overlap
6. 小 chunk 合并到邻居
"""

import re
from typing import Optional


class Chunk:
    __slots__ = ("index", "text", "heading_path", "char_start", "char_end", "oversized")

    def __init__(
        self,
        index: int,
        text: str,
        heading_path: str = "",
        char_start: int = 0,
        char_end: int = 0,
        oversized: bool = False,
    ):
        self.index = index
        self.text = text
        self.heading_path = heading_path
        self.char_start = char_start
        self.char_end = char_end
        self.oversized = oversized


class ChunkingOptions:
    def __init__(
        self,
        target_chars: int = 1000,
        max_chars: int = 1500,
        min_chars: int = 200,
        overlap_chars: int = 200,
    ):
        self.target_chars = target_chars
        self.max_chars = max(max_chars, target_chars)
        self.overlap_chars = min(overlap_chars, target_chars // 2)
        self.min_chars = min_chars


# ── Public API ──────────────────────────────────────────────────────────────


def chunk_markdown(
    content: str,
    target_chars: int = 1000,
    max_chars: int = 1500,
    min_chars: int = 200,
    overlap_chars: int = 200,
) -> list[Chunk]:
    """将 Markdown 文档分割为适合嵌入的块"""
    opts = ChunkingOptions(target_chars, max_chars, min_chars, overlap_chars)
    body, body_offset = _strip_frontmatter(content)
    if not body.strip():
        return []

    sections = _split_into_sections(body, body_offset)
    chunks: list[Chunk] = []
    running_index = 0
    for section in sections:
        for c in _chunk_section(section, opts):
            c.index = running_index
            chunks.append(c)
            running_index += 1
    return chunks


# ── Frontmatter ─────────────────────────────────────────────────────────────


def _strip_frontmatter(content: str) -> tuple[str, int]:
    if not content.startswith("---\n") and not content.startswith("---\r\n"):
        return content, 0
    # Find closing ---
    m = re.match(r"^---\n([\s\S]*?)\n---[^\S\r\n]*\n?([\s\S]*)$", content)
    if m:
        body = m.group(2)
        body_offset = len(content) - len(body)
        return body, body_offset
    return content, 0


# ── Section segmentation ────────────────────────────────────────────────────


class _Section:
    __slots__ = ("text", "body_start", "heading_path")

    def __init__(self, text: str, body_start: int, heading_path: str):
        self.text = text
        self.body_start = body_start
        self.heading_path = heading_path


def _split_into_sections(body: str, body_offset: int) -> list[_Section]:
    lines = body.split("\n")
    sections: list[_Section] = []
    headings: dict[int, str] = {}

    current_lines: list[str] = []
    current_start = body_offset
    current_heading = ""
    in_fence = False
    fence_marker = ""
    char_cursor = body_offset

    def flush():
        text = "\n".join(current_lines)
        if text.strip():
            sections.append(_Section(text, current_start, current_heading))

    for i, line in enumerate(lines):
        line_len = len(line) + (1 if i < len(lines) - 1 else 0)

        # Fenced code tracking
        fence_match = re.match(r"^(`{3,}|~{3,})", line)
        if fence_match:
            if not in_fence:
                in_fence = True
                fence_marker = fence_match.group(1)[0] * len(fence_match.group(1))
            elif line.startswith(fence_marker) and line.strip() == fence_marker:
                in_fence = False
            current_lines.append(line)
            char_cursor += line_len
            continue

        # Heading detection (outside fences)
        h_match = None if in_fence else re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if h_match:
            flush()
            level = len(h_match.group(1))
            title = h_match.group(2).strip()
            headings[level] = title
            # Clear deeper levels
            for lvl in range(level + 1, 7):
                headings.pop(lvl, None)

            path_parts = []
            for lvl in range(1, 7):
                if lvl in headings:
                    path_parts.append(f"{'#' * lvl} {headings[lvl]}")

            current_lines = [line]
            current_start = char_cursor
            current_heading = " > ".join(path_parts)
            char_cursor += line_len
            continue

        current_lines.append(line)
        char_cursor += line_len

    flush()
    return sections


# ── Section → chunks ────────────────────────────────────────────────────────


def _chunk_section(section: _Section, opts: ChunkingOptions) -> list[Chunk]:
    text = section.text
    if len(text) <= opts.target_chars:
        return [Chunk(0, text, section.heading_path, section.body_start,
                       section.body_start + len(text), False)]

    atoms = _tokenize_atoms(text)
    pieces = _split_atoms_to_pieces(atoms, opts)
    sized = _size_pieces(pieces, opts)
    merged = _merge_small(sized, opts)
    with_overlap = _apply_overlap(merged, opts)

    out: list[Chunk] = []
    for piece in with_overlap:
        out.append(Chunk(
            0, piece["text"], section.heading_path,
            section.body_start + piece["offset"],
            section.body_start + piece["offset"] + len(piece["text"]),
            len(piece["text"]) > opts.max_chars,
        ))
    return out


# ── Atom tokenization ───────────────────────────────────────────────────────


def _tokenize_atoms(text: str) -> list[dict]:
    """将文本拆分为原子块（代码块、表格、段落）"""
    atoms: list[dict] = []
    lines = text.split("\n")
    cursor = 0
    i = 0

    while i < len(lines):
        line = lines[i]

        # Fenced code block
        fence_match = re.match(r"^(`{3,}|~{3,})", line)
        if fence_match:
            marker = fence_match.group(1)[0] * len(fence_match.group(1))
            start = cursor
            body_lines = [line]
            cursor += len(line) + 1
            j = i + 1
            while j < len(lines):
                body_lines.append(lines[j])
                cursor += len(lines[j]) + 1
                if lines[j].startswith(marker) and lines[j].strip() == marker:
                    j += 1
                    break
                j += 1
            atoms.append({"text": "\n".join(body_lines), "offset": start,
                          "indivisible": True, "kind": "code"})
            i = j
            continue

        # Table
        if line.startswith("|"):
            j = i
            while j < len(lines) and lines[j].startswith("|"):
                j += 1
            if j - i >= 2:
                start = cursor
                body_lines = lines[i:j]
                content = "\n".join(body_lines)
                cursor += len(content) + (1 if j < len(lines) else 0)
                atoms.append({"text": content, "offset": start,
                              "indivisible": True, "kind": "table"})
                i = j
                continue

        # Blank line
        if not line.strip():
            cursor += len(line) + 1
            i += 1
            continue

        # Regular paragraph
        start = cursor
        body_lines: list[str] = []
        while (i < len(lines) and lines[i].strip()
               and not lines[i].startswith("|")
               and not re.match(r"^(`{3,}|~{3,})", lines[i])):
            body_lines.append(lines[i])
            cursor += len(lines[i]) + 1
            i += 1
        if body_lines:
            atoms.append({"text": "\n".join(body_lines), "offset": start,
                          "indivisible": False, "kind": "paragraph"})

    return atoms


# ── Recursive splitting ─────────────────────────────────────────────────────


def _split_atoms_to_pieces(atoms: list[dict], opts: ChunkingOptions) -> list[dict]:
    pieces: list[dict] = []
    for atom in atoms:
        if atom["indivisible"]:
            pieces.append({"text": atom["text"], "offset": atom["offset"]})
        elif len(atom["text"]) <= opts.target_chars:
            pieces.append({"text": atom["text"], "offset": atom["offset"]})
        else:
            pieces.extend(_recursive_split(atom["text"], atom["offset"], opts.target_chars))
    return pieces


def _recursive_split(text: str, base_offset: int, target: int) -> list[dict]:
    """递归分裂：段落 > 换行 > 句子 > 空格 > 硬切"""
    # Try paragraph split first
    para_pieces = re.split(r"(\n{2,})", text)
    out: list[dict] = []
    cursor = base_offset

    for chunk in para_pieces:
        if not chunk:
            continue
        if len(chunk) <= target:
            out.append({"text": chunk, "offset": cursor})
            cursor += len(chunk)
            continue
        # Try sentence split
        sent_pieces = re.split(r"([。！？!?；;]+\s*)", chunk)
        merged: list[str] = []
        buf = ""
        for piece in sent_pieces:
            if len(buf) + len(piece) <= target:
                buf += piece
            else:
                if buf:
                    merged.append(buf)
                buf = piece
        if buf:
            merged.append(buf)

        if len(merged) > 1:
            sub_cursor = cursor
            for m in merged:
                if m:
                    out.append({"text": m, "offset": sub_cursor})
                    sub_cursor += len(m)
        else:
            # Hard slice
            for j in range(0, len(chunk), target):
                piece = chunk[j:j + target]
                if piece:
                    out.append({"text": piece, "offset": cursor + j})
        cursor += len(chunk)
    return out


# ── Piece sizing ────────────────────────────────────────────────────────────


def _size_pieces(pieces: list[dict], opts: ChunkingOptions) -> list[dict]:
    out: list[dict] = []
    buf = ""
    buf_offset: Optional[int] = None
    for p in pieces:
        if not p["text"]:
            continue
        if len(p["text"]) > opts.target_chars:
            if buf and buf_offset is not None:
                out.append({"text": buf, "offset": buf_offset})
            out.append({"text": p["text"], "offset": p["offset"]})
            buf = ""
            buf_offset = None
            continue
        if buf and len(buf) + len(p["text"]) > opts.target_chars and buf_offset is not None:
            out.append({"text": buf, "offset": buf_offset})
            buf = p["text"]
            buf_offset = p["offset"]
            continue
        if not buf:
            buf_offset = p["offset"]
        buf += p["text"]
    if buf and buf_offset is not None:
        out.append({"text": buf, "offset": buf_offset})
    return out


# ── Small-chunk merge ───────────────────────────────────────────────────────


def _merge_small(pieces: list[dict], opts: ChunkingOptions) -> list[dict]:
    if len(pieces) < 2:
        return pieces
    out: list[dict] = []
    for p in pieces:
        if out and len(out[-1]["text"]) < opts.min_chars and \
                len(out[-1]["text"]) + len(p["text"]) <= opts.max_chars:
            out[-1] = {"text": out[-1]["text"] + p["text"], "offset": out[-1]["offset"]}
        else:
            out.append(p)
    return out


# ── Overlap ─────────────────────────────────────────────────────────────────


def _apply_overlap(pieces: list[dict], opts: ChunkingOptions) -> list[dict]:
    if opts.overlap_chars <= 0 or len(pieces) < 2:
        return pieces
    out = [pieces[0]]
    for i in range(1, len(pieces)):
        prev = pieces[i - 1]
        curr = pieces[i]
        tail = prev["text"][-opts.overlap_chars:]
        # Snap to sentence/word boundary
        snapped = _snap_overlap_head(tail)
        out.append({
            "text": snapped + curr["text"],
            "offset": curr["offset"] - len(snapped),
        })
    return out


def _snap_overlap_head(tail: str) -> str:
    sent_match = re.search(r"[。！？!?.;；][\s]*", tail)
    if sent_match and sent_match.end() > 0 and sent_match.end() < len(tail):
        return tail[sent_match.end():]
    ws_match = re.search(r"\s", tail)
    if ws_match and ws_match.end() < len(tail):
        return tail[ws_match.end():]
    return tail
