"""TenantStore bootstrap for serving paths.

Single seam between the in-memory dev store and a future Postgres-backed
store. Returns a fresh ``TenantStore`` for the server's lifetime.

If ``MEMNEX_DEV_KEY=1`` is set in the server's environment, registers a
local-only dev tenant and prints its API key to stderr — purely a
convenience for `memnex serve mcp --transport stdio` against an in-memory
backend. In production (Postgres-backed store), this is the swap point.
"""
from __future__ import annotations

import os
import secrets
import sys

from memnex.saas.accounts import TenantStore


def bootstrap_store_from_env() -> TenantStore:
    store = TenantStore()
    if os.getenv("MEMNEX_DEV_KEY", "").lower() in ("1", "true", "yes"):
        password = "dev-" + secrets.token_hex(8)
        tenant = store.register("dev@local.test", password)
        raw_key, _meta = store.add_key(tenant.tenant_id, label="dev")
        # Export into process env so the MCP server's _resolve_tenant can
        # find the key without the operator having to copy/paste it. Only
        # active when MEMNEX_DEV_KEY is set, so production never trips this.
        os.environ["MEMNEX_SECRET_KEY"] = raw_key
        print(
            f"[memnex] dev tenant registered: {tenant.tenant_id}\n"
            f"[memnex] MEMNEX_SECRET_KEY={raw_key}\n"
            f"[memnex] (auto-exported into this process; copy into your MCP "
            f"client config to connect from another process)",
            file=sys.stderr,
            flush=True,
        )
    return store
