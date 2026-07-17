"""Adaptive chunking: markdown sections, code (AST/definition-aware), text.

Code is chunked by *meaning*, not by a blind line count: Python via the stdlib
``ast`` (one chunk per top-level function/class, module-level code grouped),
other languages by definition boundaries. Every code chunk also carries `tags`
— the symbol name split into sub-words — which feed a node's triggers so the
Neuron→NeuRAG bridge can match a dormant concept to the right knowledge.
"""

import ast
import re
from pathlib import Path
from typing import Iterator

from .models import Chunk

# Sub-words that make poor triggers (too generic to disambiguate a topic).
_STOP = {"the", "and", "def", "class", "self", "init", "main", "get", "set",
         "str", "int", "list", "dict", "none", "true", "false", "test", "value",
         "data", "func", "return", "import", "from", "type", "new", "obj"}


def _subwords(name: str) -> list[str]:
    """snake_case + camelCase -> lowercase sub-words (find_node_by_trigger ->
    find, node, trigger)."""
    words: list[str] = []
    for part in re.split(r"[_\W]+", name):
        words += [w.lower() for w in
                  re.findall(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+", part)]
    return words


def _tags(name: str, extra: "tuple[str, ...] | list[str]" = ()) -> list[str]:
    """Trigger candidates from a symbol name (+ optional extra names)."""
    out = [name.lower(), *_subwords(name)]
    for e in extra:
        out += [e.lower(), *_subwords(e)]
    seen: list[str] = []
    for t in out:
        if len(t) >= 3 and t not in _STOP and t not in seen:
            seen.append(t)
    return seen[:8]


def _phrase_tags(phrase: str) -> list[str]:
    """Trigger candidates from a heading/section phrase."""
    words = [w.lower() for w in re.findall(r"[A-Za-z]{3,}", phrase)]
    return [w for w in dict.fromkeys(words) if w not in _STOP][:6]


def _module_tags(text: str) -> list[str]:
    """Top-level imported module names — a Python module chunk's fingerprint."""
    names: list[str] = []
    for m in re.finditer(r"^\s*(?:from\s+([\w.]+)|import\s+([\w.]+))", text, re.M):
        mod = (m.group(1) or m.group(2) or "").split(".")[0].lower()
        if len(mod) >= 3 and mod not in _STOP and mod not in names:
            names.append(mod)
    return names[:8]


def chunk_markdown(filepath: Path) -> list[Chunk]:
    lines = filepath.read_text(encoding="utf-8").split("\n")
    chunks: list[Chunk] = []
    current_section = "intro"
    current_lines: list[str] = []
    chunk_index = 0

    def flush():
        nonlocal chunk_index
        text = "\n".join(current_lines).strip()
        if len(text) > 20:
            chunks.append(Chunk(text=text, source=str(filepath),
                                section=current_section, chunk_index=chunk_index,
                                tags=_phrase_tags(current_section)))
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


def chunk_python_ast(filepath: Path) -> list[Chunk]:
    """One chunk per top-level function/class; module-level code grouped.

    Decorators are kept with their target. Falls back to line chunking if the
    file doesn't parse (partial edits, non-CPython syntax)."""
    source = filepath.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return chunk_lines(filepath)
    lines = source.split("\n")
    chunks: list[Chunk] = []
    idx = 0
    module_buf: list[str] = []

    def span(node) -> tuple[int, int]:
        start = node.lineno
        if getattr(node, "decorator_list", None):
            start = min(d.lineno for d in node.decorator_list)
        return start, getattr(node, "end_lineno", node.lineno)

    def flush_module():
        nonlocal idx
        text = "\n".join(module_buf).strip()
        if len(text) > 20:
            chunks.append(Chunk(text=text, source=str(filepath), section="module",
                                chunk_index=idx, tags=_module_tags(text)))
            idx += 1
        module_buf.clear()

    for node in tree.body:
        start, end = span(node)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            flush_module()
            text = "\n".join(lines[start - 1:end]).strip()
            if not text:
                continue
            kind = "class" if isinstance(node, ast.ClassDef) else "def"
            extra = ([n.name for n in node.body
                      if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))][:6]
                     if isinstance(node, ast.ClassDef) else [])
            chunks.append(Chunk(text=text, source=str(filepath),
                                section=f"{kind} {node.name}", chunk_index=idx,
                                tags=_tags(node.name, extra)))
            idx += 1
        else:
            module_buf += lines[start - 1:end]

    flush_module()
    return chunks or chunk_lines(filepath)


# Definition keywords across the languages we support (kt/java/ts/js/rs/go).
_DEF_RE = re.compile(
    r"^\s{0,4}(?:export\s+|default\s+|pub\s+|public\s+|private\s+|protected\s+|"
    r"static\s+|async\s+|final\s+|open\s+|suspend\s+|abstract\s+)*"
    r"(function|func|fn|def|class|interface|type|struct|impl|enum|object|trait)"
    r"\b[ \t]*([A-Za-z_]\w*)?"
)


def chunk_code_generic(filepath: Path, hard_cap: int = 160) -> list[Chunk]:
    """Definition-aware chunking for non-Python code: a new chunk starts at each
    top-level definition, with a size cap so a giant body can't run away."""
    lines = filepath.read_text(encoding="utf-8").split("\n")
    chunks: list[Chunk] = []
    cur: list[str] = []
    state = {"section": "top", "tags": [], "idx": 0}

    def flush():
        text = "\n".join(cur).strip()
        if text:
            chunks.append(Chunk(text=text, source=str(filepath),
                                section=state["section"], chunk_index=state["idx"],
                                tags=list(state["tags"])))
            state["idx"] += 1
        cur.clear()

    for line in lines:
        m = _DEF_RE.match(line)
        if m and cur:
            flush()
        if m:
            kw, name = m.group(1), (m.group(2) or "")
            state["section"] = f"{kw} {name}".strip()
            state["tags"] = _tags(name) if name else [kw]
        if len(cur) >= hard_cap:
            flush()
        cur.append(line)

    flush()
    return chunks


def chunk_lines(filepath: Path, max_lines: int = 60) -> list[Chunk]:
    """Plain size-based chunking — text and config files with no code structure."""
    lines = filepath.read_text(encoding="utf-8").split("\n")
    chunks: list[Chunk] = []
    buf: list[str] = []
    idx = 0

    def flush():
        nonlocal idx
        text = "\n".join(buf).strip()
        if text:
            chunks.append(Chunk(text=text, source=str(filepath),
                                section=f"lines {idx * max_lines}-{(idx + 1) * max_lines}",
                                chunk_index=idx))
            idx += 1

    for line in lines:
        buf.append(line)
        if len(buf) >= max_lines:
            flush()
            buf = []
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
            chunks.append(Chunk(text=text, source=str(filepath),
                                section=f"page {page_num + 1}", chunk_index=page_num))
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
            chunks.append(Chunk(text=text, source=str(filepath),
                                section=current_section, chunk_index=chunk_index,
                                tags=_phrase_tags(current_section)))
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
    if suffix == ".py":
        return chunk_python_ast(filepath)
    if suffix in (".kt", ".java", ".ts", ".js", ".rs", ".go"):
        return chunk_code_generic(filepath)
    if suffix == ".pdf":
        return chunk_pdf(filepath)
    if suffix == ".docx":
        return chunk_docx(filepath)
    if suffix in (".txt", ".rst", ".yaml", ".yml", ".toml", ".json", ".xml"):
        return chunk_lines(filepath)
    return []


def scan_directory(root: Path) -> Iterator[Path]:
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in _SUPPORTED_EXTENSIONS:
            yield path


_SUPPORTED_EXTENSIONS = {".md", ".py", ".kt", ".java", ".ts", ".js", ".rs", ".go",
                         ".pdf", ".docx", ".txt", ".rst", ".yaml", ".yml", ".toml", ".json", ".xml"}
