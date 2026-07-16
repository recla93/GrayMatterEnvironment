"""Adaptive chunking: markdown sections, code files, plain text."""

import re
from pathlib import Path
from typing import Iterator

from .models import Chunk


def chunk_markdown(filepath: Path) -> list[Chunk]:
    content = filepath.read_text(encoding="utf-8")
    lines = content.split("\n")

    chunks: list[Chunk] = []
    current_section = "intro"
    current_lines: list[str] = []
    chunk_index = 0

    def flush():
        nonlocal chunk_index
        text = "\n".join(current_lines).strip()
        if len(text) > 20:
            chunks.append(Chunk(
                text=text,
                source=str(filepath),
                section=current_section,
                chunk_index=chunk_index,
            ))
            chunk_index += 1

    for line in lines:
        heading = re.match(r"^#{2,4}\s+(.+)$", line)
        if heading:
            flush()
            current_lines = []
            current_section = heading.group(1).strip()
        current_lines.append(line)

    flush()
    return chunks


def chunk_code(filepath: Path) -> list[Chunk]:
    content = filepath.read_text(encoding="utf-8")
    lines = content.split("\n")

    chunks: list[Chunk] = []
    current_lines: list[str] = []
    chunk_index = 0
    max_lines = 50

    def flush():
        nonlocal chunk_index
        text = "\n".join(current_lines).strip()
        if text:
            chunks.append(Chunk(
                text=text,
                source=str(filepath),
                section=f"lines {chunk_index * max_lines}-{(chunk_index + 1) * max_lines}",
                chunk_index=chunk_index,
            ))
            chunk_index += 1

    for line in lines:
        current_lines.append(line)
        if len(current_lines) >= max_lines:
            flush()
            current_lines = []

    flush()
    return chunks


def chunk_pdf(filepath: Path) -> list[Chunk]:
    try:
        import fitz  # PyMuPDF
    except ImportError:
        raise ImportError("pip install neurag[pdf] for PDF support")

    doc = fitz.open(filepath)
    chunks: list[Chunk] = []
    for page_num, page in enumerate(doc):
        text = page.get_text().strip()
        if text:
            chunks.append(Chunk(
                text=text,
                source=str(filepath),
                section=f"page {page_num + 1}",
                chunk_index=page_num,
            ))
    doc.close()
    return chunks


def chunk_docx(filepath: Path) -> list[Chunk]:
    try:
        import docx  # python-docx
    except ImportError:
        raise ImportError("pip install neurag[docx] for Word (.docx) support")

    document = docx.Document(str(filepath))
    chunks: list[Chunk] = []
    current_section = "intro"
    current_lines: list[str] = []
    chunk_index = 0

    def flush():
        nonlocal chunk_index
        text = "\n".join(current_lines).strip()
        if len(text) > 20:
            chunks.append(Chunk(
                text=text,
                source=str(filepath),
                section=current_section,
                chunk_index=chunk_index,
            ))
            chunk_index += 1

    for para in document.paragraphs:
        style = (para.style.name if para.style else "") or ""
        if style.startswith("Heading") and para.text.strip():
            flush()
            current_lines = []
            current_section = para.text.strip()
        current_lines.append(para.text)

    flush()
    return chunks


def chunk_file(filepath: Path) -> list[Chunk]:
    suffix = filepath.suffix.lower()
    if suffix == ".md":
        return chunk_markdown(filepath)
    if suffix in (".py", ".kt", ".java", ".ts", ".js", ".rs", ".go"):
        return chunk_code(filepath)
    if suffix == ".pdf":
        return chunk_pdf(filepath)
    if suffix == ".docx":
        return chunk_docx(filepath)
    if suffix in (".txt", ".rst", ".yaml", ".yml", ".toml", ".json", ".xml"):
        return chunk_code(filepath)
    return []


def scan_directory(root: Path) -> Iterator[Path]:
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in _SUPPORTED_EXTENSIONS:
            yield path


_SUPPORTED_EXTENSIONS = {".md", ".py", ".kt", ".java", ".ts", ".js", ".rs", ".go",
                         ".pdf", ".docx", ".txt", ".rst", ".yaml", ".yml", ".toml", ".json", ".xml"}
