import io
import pytest
from concierge.materials import extract_text, MaterialError


def _pdf_bytes(text):
    from pypdf import PdfWriter
    import io as _io
    w = PdfWriter()
    page = w.add_blank_page(width=200, height=200)
    # pypdf can't easily write text; use a txt-based assertion for pdf via
    # a real minimal pdf produced by reportlab-free approach: instead test
    # that a blank pdf raises MaterialError for empty text.
    buf = _io.BytesIO()
    w.write(buf)
    return buf.getvalue()


def _docx_bytes(text):
    import docx, io as _io
    d = docx.Document()
    d.add_paragraph(text)
    buf = _io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def test_txt_and_md_extraction():
    assert extract_text("notas.txt", "olá mundo".encode()) == "olá mundo"
    assert extract_text("guia.md", b"# Title\nbody") == "# Title\nbody"


def test_txt_latin1_fallback():
    assert "ção" in extract_text("legado.txt", "validação".encode("latin-1"))


def test_docx_extraction():
    data = _docx_bytes("Business Model Canvas em nove blocos")
    assert "nove blocos" in extract_text("manual.docx", data)


def test_blank_pdf_raises_empty():
    with pytest.raises(MaterialError):
        extract_text("vazio.pdf", _pdf_bytes(""))


def test_unsupported_extension_raises():
    with pytest.raises(MaterialError):
        extract_text("planilha.xlsx", b"whatever")
