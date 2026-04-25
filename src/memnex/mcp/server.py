"""MCP server boot.

Boot-time sequence:

1. Read tenant's MCP config (``MEMNEX_SECRET_KEY``, ``MEMNEX_CHANNEL``,
   optional ``MEMNEX_LLM_PROVIDER``).
2. Read server-only infra from env (``MEMNEX_POSTGRES_URL`` etc.) via
   :func:`memnex.server_config.server_infra`.
3. Resolve the API key against the tenant store. Extract ``tenant_id``.
4. Build a Memnex client scoped to the tenant.
5. Expose tools via :class:`McpContext`. Every tool call scopes to
   ``(tenant_id, user_id)`` where ``user_id`` comes from the tool args.
"""
from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING

from memnex.client import Memnex
from memnex.config import MemnexConfig
from memnex.mcp.tools import TOOL_SCHEMAS, McpContext, build_tool_handlers
from memnex.mcp.validation import ValidationError
from memnex.saas.accounts import TenantStore
from memnex.saas.keys import parse_api_key, verify_api_key
from memnex.server_config import server_infra

if TYPE_CHECKING:
    from mcp.server import Server


async def _resolve_tenant(store: TenantStore) -> tuple[str, str]:
    """Return ``(tenant_id, channel)``."""
    raw_key = os.getenv("MEMNEX_SECRET_KEY")
    if not raw_key:
        raise RuntimeError("MEMNEX_SECRET_KEY is required in MCP config")
    try:
        _env, key_id, _raw = parse_api_key(raw_key)
    except ValueError as e:
        raise RuntimeError(f"malformed MEMNEX_SECRET_KEY: {e}") from e

    resolved = store.resolve_key(key_id)
    if not resolved:
        raise RuntimeError("unknown API key")
    tenant, meta = resolved
    if not verify_api_key(raw_key, meta):
        raise RuntimeError("API key verification failed")
    if tenant.disabled:
        raise RuntimeError("tenant disabled")

    channel = os.getenv("MEMNEX_CHANNEL", "app")
    return tenant.tenant_id, channel


async def build_mcp_server(store: TenantStore) -> Server:
    try:
        from mcp.server import Server
        from mcp.types import (
            GetPromptResult,
            Prompt,
            PromptArgument,
            PromptMessage,
            Resource,
            ResourceTemplate,
            TextContent,
            Tool,
        )
        from pydantic import AnyUrl
    except ImportError as e:
        raise ImportError("`pip install memnex[mcp]`.") from e

    tenant_id, channel = await _resolve_tenant(store)

    infra = server_infra()
    cfg = MemnexConfig(
        tenant_id=tenant_id,
        postgres_url=infra.postgres_url,
        redis_url=infra.redis_url,
        qdrant_url=infra.qdrant_url,
        llm_provider=os.getenv("MEMNEX_LLM_PROVIDER", "none"),  # type: ignore[arg-type]
    )
    mx = await Memnex.create(config=cfg)
    mctx = McpContext(mx=mx, tenant_id=tenant_id, channel=channel)

    server: Server = Server("memnex")
    handlers = build_tool_handlers(mctx)

    from memnex.mcp.prompts import PROMPTS, get_prompt_messages
    from memnex.mcp.resources import (
        ResourceError,
        ResourceRouter,
        resource_templates,
        static_resources,
    )

    resource_router = ResourceRouter(mctx)

    @server.list_tools()
    async def _list() -> list[Tool]:
        return [
            Tool(
                name=t["name"],
                description=t["description"],
                inputSchema=t["inputSchema"],
            )
            for t in TOOL_SCHEMAS
        ]

    @server.list_resources()
    async def _list_resources() -> list[Resource]:
        return [
            Resource(
                uri=AnyUrl(r["uri"]),
                name=r["name"],
                title=r.get("title"),
                description=r["description"],
                mimeType=r["mimeType"],
            )
            for r in static_resources()
        ]

    @server.list_resource_templates()
    async def _list_resource_templates() -> list[ResourceTemplate]:
        return [
            ResourceTemplate(
                uriTemplate=t["uriTemplate"],
                name=t["name"],
                title=t.get("title"),
                description=t["description"],
                mimeType=t["mimeType"],
            )
            for t in resource_templates()
        ]

    @server.read_resource()
    async def _read_resource(uri: AnyUrl) -> str:
        try:
            content, _mime = await resource_router.read(str(uri))
            return content
        except ResourceError as e:
            return json.dumps({"error": "not_found", "detail": str(e)})
        except Exception as e:
            return json.dumps({"error": "internal", "detail": str(e)})

    @server.list_prompts()
    async def _list_prompts() -> list[Prompt]:
        return [
            Prompt(
                name=p["name"],
                description=p["description"],
                arguments=[
                    PromptArgument(
                        name=a["name"],
                        description=a["description"],
                        required=a.get("required", False),
                    )
                    for a in p.get("arguments", [])
                ],
            )
            for p in PROMPTS
        ]

    @server.get_prompt()
    async def _get_prompt(
        name: str, arguments: dict[str, str] | None
    ) -> GetPromptResult:
        try:
            messages = get_prompt_messages(name, arguments or {})
        except KeyError as e:
            raise ValueError(f"unknown prompt: {name}") from e
        return GetPromptResult(
            description=next(
                (p["description"] for p in PROMPTS if p["name"] == name), name
            ),
            messages=[
                PromptMessage(
                    role=m["role"],
                    content=TextContent(type="text", text=m["content"]),
                )
                for m in messages
            ],
        )

    @server.call_tool()
    async def _call(name: str, arguments: dict) -> list[TextContent]:
        handler = handlers.get(name)
        if handler is None:
            return [TextContent(
                type="text",
                text=json.dumps({"error": "unknown_tool", "detail": name}),
            )]
        try:
            result = await handler(**(arguments or {}))
            return [TextContent(type="text", text=json.dumps(result, default=str))]
        except ValidationError as e:
            return [TextContent(
                type="text",
                text=json.dumps({"error": "bad_request", "detail": str(e)}),
            )]
        except PermissionError as e:
            return [TextContent(
                type="text",
                text=json.dumps({"error": "forbidden", "detail": str(e)}),
            )]
        except Exception as e:
            return [TextContent(
                type="text",
                text=json.dumps({"error": "internal", "detail": str(e)}),
            )]

    return server


async def run_stdio(store: TenantStore) -> None:
    from mcp.server.stdio import stdio_server
    server = await build_mcp_server(store)
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


async def run_streamable_http(
    store: TenantStore, *, host: str = "0.0.0.0", port: int = 8500
) -> None:
    try:
        import uvicorn
        from fastapi import FastAPI
        from mcp.server.streamable_http import streamable_http_app
    except ImportError as e:
        raise ImportError("`pip install memnex[api,mcp]`.") from e

    server = await build_mcp_server(store)
    app = FastAPI(title="Memnex MCP + API")
    app.mount("/mcp", streamable_http_app(server))

    from memnex.saas.routes import mount_saas
    mount_saas(app, store=store)

    config = uvicorn.Config(app, host=host, port=port, log_level="info")
    await uvicorn.Server(config).serve()
