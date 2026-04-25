"""MCP boundary tests for structured FactInput validation."""
from __future__ import annotations

import pytest

from memnex.mcp.validation import FactInput, ValidationError, validate_facts


def test_accepts_plain_string_facts():
    out = validate_facts(["Customer wants a refund"])
    assert out == ["Customer wants a refund"]


def test_accepts_structured_fact_dict():
    out = validate_facts([
        {
            "fact": "Customer wants to cancel order XYZ",
            "type": "intent",
            "entities": ["order:XYZ"],
            "confidence": 0.95,
        }
    ])
    assert len(out) == 1
    assert isinstance(out[0], FactInput)
    assert out[0].type == "intent"
    assert out[0].entities == ["order:XYZ"]
    assert out[0].confidence == 0.95


def test_accepts_mixed_strings_and_structured():
    out = validate_facts([
        "Plain string fact",
        {"fact": "Structured", "type": "preference", "entities": [], "confidence": 0.8},
    ])
    assert isinstance(out[0], str)
    assert isinstance(out[1], FactInput)


def test_rejects_unknown_type():
    with pytest.raises(ValidationError) as exc:
        validate_facts([{"fact": "x", "type": "event", "entities": [], "confidence": 1.0}])
    assert "type" in str(exc.value)


def test_rejects_missing_required_field():
    with pytest.raises(ValidationError) as exc:
        validate_facts([{"type": "intent", "entities": [], "confidence": 0.9}])
    assert "fact" in str(exc.value)


def test_rejects_out_of_range_confidence():
    with pytest.raises(ValidationError):
        validate_facts([{"fact": "x", "type": "intent", "entities": [], "confidence": 1.5}])


def test_rejects_extra_fields():
    # extra=forbid on the pydantic model means typos in field names surface.
    with pytest.raises(ValidationError):
        validate_facts([{
            "fact": "x", "type": "intent", "entities": [],
            "confidence": 0.9, "priority": "high",  # not part of the contract
        }])


def test_rejects_non_string_non_dict_item():
    with pytest.raises(ValidationError):
        validate_facts([123])


def test_defaults_are_applied():
    fi = FactInput(fact="hello", type="profile")
    assert fi.entities == []
    assert fi.confidence == 0.9
