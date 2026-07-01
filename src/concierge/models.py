from enum import Enum
from pydantic import BaseModel


class ItemType(str, Enum):
    DECISION = "decision"
    HYPOTHESIS = "hypothesis"
    PREMISE = "premise"
    RISK = "risk"
    TASK = "task"
    LEARNING = "learning"


class ItemStatus(str, Enum):
    ACTIVE = "active"
    VALIDATED = "validated"
    DISCARDED = "discarded"
    SUPERSEDED = "superseded"


class ProjectMode(str, Enum):
    SILENT = "silent"
    MODERATE = "moderate"
    ACTIVE = "active"


class ExtractedItem(BaseModel):
    type: ItemType
    content: str
    confidence: float


class ExtractionResult(BaseModel):
    items: list[ExtractedItem]


class CoherenceVerdict(BaseModel):
    contradicts: bool
    item_content: str | None = None
    reason: str
    confidence: float


class CanvasBlockUpdate(BaseModel):
    block_name: str
    content: str


class CanvasUpdateResult(BaseModel):
    blocks: list[CanvasBlockUpdate]


class ItemTransition(BaseModel):
    item_id: int
    new_status: ItemStatus
    supersedes_id: int | None = None


class ReconciliationResult(BaseModel):
    transitions: list[ItemTransition]


class MaterialType(str, Enum):
    CANVAS_GUIDE = "canvas_guide"
    VALIDATION_GUIDE = "validation_guide"
    METHODOLOGY = "methodology"
    CUSTOM_FRAMEWORK = "custom_framework"
    GENERIC = "generic"


class ClassificationResult(BaseModel):
    material_type: MaterialType
