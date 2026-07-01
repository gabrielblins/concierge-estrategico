import io


class MaterialError(Exception):
    """User-facing ingestion problem (unsupported format, unreadable file)."""


def _from_pdf(data: bytes) -> str:
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def _from_docx(data: bytes) -> str:
    import docx
    document = docx.Document(io.BytesIO(data))
    return "\n".join(p.text for p in document.paragraphs)


def _from_text(data: bytes) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1")


_PARSERS = {".pdf": _from_pdf, ".docx": _from_docx, ".txt": _from_text, ".md": _from_text}


def extract_text(filename: str, data: bytes) -> str:
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    parser = _PARSERS.get(ext)
    if parser is None:
        raise MaterialError(
            f"Formato não suportado: '{ext or filename}'. Aceito: PDF, TXT, MD, DOCX."
        )
    try:
        text = parser(data)
    except MaterialError:
        raise
    except Exception as e:
        raise MaterialError(f"Não consegui ler o arquivo '{filename}': {e}") from e
    if not text.strip():
        raise MaterialError(f"O arquivo '{filename}' não contém texto extraível.")
    return text
