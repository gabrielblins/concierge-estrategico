import io
import pytest
import chromadb
import sqlite3
from concierge.materials import (
    extract_text, MaterialError, classify, types_for_module, ROUTING, CAPABILITIES, MaterialService,
)
from concierge.models import MaterialType
from concierge.storage import Storage
from concierge.knowledge import KnowledgeBase


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


def test_routing_covers_all_types_and_inverts():
    assert set(ROUTING) == set(MaterialType)
    assert set(CAPABILITIES) == set(MaterialType)
    assert "updater" in ROUTING[MaterialType.CANVAS_GUIDE]
    guardian_types = types_for_module("guardian")
    assert set(guardian_types) == {
        "validation_guide", "methodology", "custom_framework", "generic"
    }
    assert types_for_module("updater") == ["canvas_guide", "custom_framework"]


def test_classify_returns_type_and_falls_back(fake_llm):
    llm = fake_llm(responses=[{"material_type": "validation_guide"}])
    assert classify(llm, "guia.pdf", "como validar hipóteses...") == MaterialType.VALIDATION_GUIDE
    bad = fake_llm(responses=[{"material_type": "zzz"}, {"material_type": "zzz"}])
    assert classify(bad, "x.txt", "abc") == MaterialType.GENERIC


def test_material_service_end_to_end(fake_llm):
    conn = sqlite3.connect(":memory:")
    st = Storage(conn); st.init_schema()
    pid = st.get_or_create_project(100, "Acme")
    kb = KnowledgeBase(chromadb.EphemeralClient())
    llm = fake_llm(responses=[{"material_type": "canvas_guide"}])
    svc = MaterialService(llm, kb, st)
    mtype, chunks = svc.add_material(pid, "manual.txt", "os nove blocos do canvas " * 50)
    assert mtype == MaterialType.CANVAS_GUIDE
    assert chunks >= 1
    docs = st.list_knowledge_docs(pid)
    assert docs[0]["material_type"] == "canvas_guide"
    assert "blocos" in kb.query(pid, "blocos", material_types=["canvas_guide"])


def test_participant_routed_to_all_types():
    assert set(types_for_module("participant")) == {
        "canvas_guide", "validation_guide", "methodology",
        "custom_framework", "generic",
    }
