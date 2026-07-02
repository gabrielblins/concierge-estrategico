import io
from concierge.llm.client import call_validated
from concierge.models import ClassificationResult, MaterialType


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


ROUTING = {
    MaterialType.CANVAS_GUIDE: {"updater", "participant"},
    MaterialType.VALIDATION_GUIDE: {"guardian", "reconciler", "participant"},
    MaterialType.METHODOLOGY: {"extractor", "guardian", "participant"},
    MaterialType.CUSTOM_FRAMEWORK: {"extractor", "updater", "guardian", "reconciler", "participant"},
    MaterialType.GENERIC: {"guardian", "participant"},
}

CAPABILITIES = {
    MaterialType.CANVAS_GUIDE: "o canvas passa a seguir as definições deste manual",
    MaterialType.VALIDATION_GUIDE: "o guardião agora cobra experimentos; validações seguem este método",
    MaterialType.METHODOLOGY: "as análises passam a usar os conceitos deste método",
    MaterialType.CUSTOM_FRAMEWORK: "este framework vira lente de todas as análises",
    MaterialType.GENERIC: "material disponível como contexto geral",
}

CLASSIFY_SYSTEM = (
    "You classify startup reference material. Given a filename and the opening "
    "text, return JSON {\"material_type\": one of canvas_guide|validation_guide|"
    "methodology|custom_framework|generic}. canvas_guide = manuals about business "
    "model canvas blocks; validation_guide = how to validate hypotheses/run "
    "experiments; methodology = named methods like Design Thinking or Lean; "
    "custom_framework = the team's own internal framework; generic = anything else."
)


def types_for_module(module: str) -> list[str]:
    return sorted(t.value for t, mods in ROUTING.items() if module in mods)


def classify(llm, filename: str, text: str) -> MaterialType:
    user = f"FILENAME: {filename}\n\nOPENING TEXT:\n{text[:2000]}"
    result = call_validated(llm, CLASSIFY_SYSTEM, user, ClassificationResult)
    if result is None:
        return MaterialType.GENERIC
    return result.material_type


class MaterialService:
    def __init__(self, llm, knowledge, storage):
        self.llm = llm
        self.knowledge = knowledge
        self.storage = storage

    def add_material(self, project_id: int, filename: str, text: str) -> tuple[MaterialType, int]:
        mtype = classify(self.llm, filename, text)
        chunks = self.knowledge.ingest(
            project_id, filename, text, material_type=mtype.value
        )
        self.storage.add_knowledge_doc(project_id, filename, mtype.value, chunks)
        return mtype, chunks
