"""Plain text from notes and exam papers: PDF, Word, PowerPoint, HTML, text."""

import logging
import os

log = logging.getLogger(__name__)


def _pdf(path: str) -> str:
    from pypdf import PdfReader

    pages = [(p.extract_text() or "") for p in PdfReader(path).pages]
    blank = [i for i, t in enumerate(pages) if not t.strip()]
    if blank:
        try:  # pypdf misses some layouts; pdfplumber often recovers them
            import pdfplumber

            with pdfplumber.open(path) as pdf:
                for i in blank:
                    pages[i] = pdf.pages[i].extract_text() or ""
        except Exception as e:
            log.warning("pdfplumber fallback failed: %s", e)
    return "\n\n".join(pages)


def _docx(path: str) -> str:
    import docx

    d = docx.Document(path)
    parts = [p.text for p in d.paragraphs if p.text.strip()]
    for table in d.tables:
        for row in table.rows:
            parts.append(" | ".join(c.text.strip() for c in row.cells))
    return "\n".join(parts)


def _pptx(path: str) -> str:
    from pptx import Presentation

    slides = []
    for slide in Presentation(path).slides:
        texts = [sh.text_frame.text for sh in slide.shapes if getattr(sh, "has_text_frame", False) and sh.text_frame.text.strip()]
        slides.append("\n".join(texts))
    return "\n\n".join(slides)


def _html(path: str) -> str:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(open(path, encoding="utf-8", errors="ignore").read(), "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    return soup.get_text("\n", strip=True)


def extract_text(path: str, filename: str | None = None) -> str | None:
    ext = (filename or os.path.basename(path)).lower().rsplit(".", 1)[-1]
    handlers = {"pdf": _pdf, "docx": _docx, "pptx": _pptx, "html": _html, "htm": _html}
    if ext in handlers:
        return handlers[ext](path)
    if ext in ("txt", "md"):
        return open(path, encoding="utf-8", errors="ignore").read()
    return None
