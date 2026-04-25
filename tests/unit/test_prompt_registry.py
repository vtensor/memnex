"""Prompt registry shape and dispatcher behaviour."""
from __future__ import annotations

import pytest

from memnex.mcp.prompts import PROMPTS, get_prompt_messages


def test_three_prompts_registered():
    names = [p["name"] for p in PROMPTS]
    assert names == ["memory-writer", "memory-reader", "hallucination-check"]


def test_all_prompts_have_required_fields():
    for p in PROMPTS:
        assert "name" in p
        assert "description" in p
        assert isinstance(p.get("arguments", []), list)
        for a in p.get("arguments", []):
            assert "name" in a
            assert "description" in a


def test_memory_writer_default_role():
    msgs = get_prompt_messages("memory-writer", {})
    assert len(msgs) == 1
    assert msgs[0]["role"] == "user"
    assert "support agent" in msgs[0]["content"]


def test_memory_writer_custom_role():
    msgs = get_prompt_messages("memory-writer", {"agent_role": "clinic intake"})
    assert "clinic intake" in msgs[0]["content"]


def test_memory_writer_mentions_all_5_fact_types():
    msgs = get_prompt_messages("memory-writer", {})
    body = msgs[0]["content"]
    for t in ("intent", "preference", "issue", "resolution", "profile"):
        assert t in body


def test_memory_reader_uses_target_format():
    msgs = get_prompt_messages("memory-reader", {"target_format": "voice"})
    assert "voice" in msgs[0]["content"]


def test_hallucination_check_includes_draft():
    msgs = get_prompt_messages(
        "hallucination-check",
        {"agent_output": "Your order #4521 has shipped."},
    )
    assert "#4521" in msgs[0]["content"]


def test_unknown_prompt_raises_keyerror():
    with pytest.raises(KeyError):
        get_prompt_messages("does-not-exist", {})


def test_all_prompt_bodies_under_8k():
    for p in PROMPTS:
        msgs = get_prompt_messages(p["name"], {"agent_output": "test"})
        for m in msgs:
            assert len(m["content"]) < 8192, f"{p['name']} body too large"
