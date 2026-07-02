import pytest
from pydantic import ValidationError
from concierge.models import (
    ItemType, ItemStatus, ProjectMode,
    ExtractedItem, ExtractionResult, CoherenceVerdict,
    CanvasBlockUpdate, CanvasUpdateResult,
)


def test_item_type_values():
    assert ItemType.HYPOTHESIS == "hypothesis"
    assert {t.value for t in ItemType} == {
        "decision", "hypothesis", "premise", "risk", "task", "learning"
    }


def test_extraction_result_parses_valid_json():
    data = {"items": [{"type": "decision", "content": "Focus on segment Y", "confidence": 0.9}]}
    result = ExtractionResult.model_validate(data)
    assert result.items[0].type == ItemType.DECISION
    assert result.items[0].confidence == 0.9


def test_extracted_item_rejects_bad_type():
    with pytest.raises(ValidationError):
        ExtractedItem.model_validate({"type": "nonsense", "content": "x", "confidence": 0.5})


def test_coherence_verdict_allows_null_item():
    v = CoherenceVerdict.model_validate(
        {"contradicts": False, "item_content": None, "reason": "no conflict", "confidence": 0.2}
    )
    assert v.contradicts is False
    assert v.item_content is None


def test_material_type_values():
    from concierge.models import MaterialType
    assert {t.value for t in MaterialType} == {
        "canvas_guide", "validation_guide", "methodology",
        "custom_framework", "generic",
    }


def test_classification_result_parses_and_rejects():
    from concierge.models import ClassificationResult, MaterialType
    ok = ClassificationResult.model_validate({"material_type": "validation_guide"})
    assert ok.material_type == MaterialType.VALIDATION_GUIDE
    with pytest.raises(ValidationError):
        ClassificationResult.model_validate({"material_type": "cookbook"})
