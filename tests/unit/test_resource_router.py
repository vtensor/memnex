"""URI parsing for the MCP resource router."""
from __future__ import annotations

import json

import pytest

from memnex import Memnex, MemnexConfig
from memnex.mcp.resources import (
    ResourceError,
    ResourceRouter,
    resource_templates,
    static_resources,
)
from memnex.mcp.tools import McpContext


@pytest.fixture
async def router():
    mx = await Memnex.create(config=MemnexConfig(tenant_id="t_router_test"))
    ctx = McpContext(mx=mx, tenant_id="t_router_test", channel="web")
    try:
        yield ResourceRouter(ctx)
    finally:
        await mx.close()


def test_static_resources_have_required_fields():
    for r in static_resources():
        for k in ("uri", "name", "description", "mimeType"):
            assert k in r, f"missing {k} in {r}"


def test_resource_templates_have_required_fields():
    for t in resource_templates():
        for k in ("uriTemplate", "name", "description", "mimeType"):
            assert k in t, f"missing {k} in {t}"


async def test_schema_resource_returns_markdown(router):
    content, mime = await router.read("memnex://schema/fact-types")
    assert mime == "text/markdown"
    assert "intent" in content
    assert "preference" in content
    assert "issue" in content
    assert "resolution" in content
    assert "profile" in content


async def test_tenant_stats_returns_json(router):
    content, mime = await router.read("memnex://tenants/me/stats")
    assert mime == "application/json"
    parsed = json.loads(content)
    assert isinstance(parsed, dict)


async def test_user_memories_returns_empty_for_unknown_user(router):
    content, mime = await router.read("memnex://users/unknown_u/memories")
    assert mime == "application/json"
    parsed = json.loads(content)
    assert parsed["user_id"] == "unknown_u"
    assert parsed["count"] == 0
    assert parsed["memories"] == []


async def test_user_memories_returns_facts_after_write(router):
    await router._ctx.mx.user_write(
        user_id="u1", channel="web",
        facts=["Customer prefers morning calls"],
    )
    content, _ = await router.read("memnex://users/u1/memories")
    parsed = json.loads(content)
    assert parsed["count"] >= 1
    assert any("morning" in m["fact"].lower() for m in parsed["memories"])


async def test_unknown_uri_raises(router):
    with pytest.raises(ResourceError):
        await router.read("memnex://nonsense/path")


async def test_wrong_scheme_raises(router):
    with pytest.raises(ResourceError):
        await router.read("file:///etc/passwd")


async def test_template_must_have_user_id(router):
    # malformed - no user_id segment
    with pytest.raises(ResourceError):
        await router.read("memnex://users//memories")
