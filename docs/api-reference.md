# API reference

Memnex exposes its functionality through three surfaces. **Pick the one that matches your role.**

| Surface | Audience | Use this if you... |
|---|---|---|
| **MCP** | Tenants (the agent operator) | Are integrating an AI agent — Claude Desktop, Cursor, LangGraph, etc. — with Memnex. The default and recommended path. |
| **REST** | Tenants who can't use MCP | Are calling Memnex from a non-MCP runtime (e.g. an existing backend service in Go, Node, Python). |
| **Python embedded** | Operators and contributors only | Are running Memnex yourself and want to call the engine in-process. Not a tenant integration path. |
| **CLI** | Operators only | Are administering a Memnex deployment from the shell. |

Tenants almost always want **MCP**. The full MCP API (tools + resources + prompts) is in [mcp.md](mcp.md). The sections below are the alternatives.

---

## REST

Base URL: `http://<your-memnex-host>:8500/api/v1`. Memnex is self-hosted today — deploy `memnex serve rest` and the URL is wherever you put it.

Auth: pass your tenant API key in the `X-Memnex-API-Key` header. Memnex resolves it to a tenant id server-side; you never see or supply the tenant id.

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/memory/write` | Write structured facts |
| `GET` / `POST` | `/memory/read` | Read formatted context (token-budgeted) |
| `POST` | `/memory/search` | Semantic search |
| `POST` | `/identity/resolve` | Resolve identifier → customer id |
| `POST` | `/identity/link` | Link two identifiers to one customer |
| `DELETE` | `/customer/{id}` | GDPR forget — purges all stores |
| `GET` | `/customer/{id}/export` | Export customer data (GDPR) |
| `GET` | `/customer/{id}/timeline` | Interaction timeline |
| `GET` | `/stats` | Per-tenant counts |
| `GET` | `/health` | Health check (no auth) |
| `GET` | `/metrics` | Prometheus metrics (operator-only) |

Errors are JSON: `{"error": "bad_request", "detail": "..."}`. Injection-pattern content is rejected with `bad_request`.

### Write request shape

```jsonc
POST /api/v1/memory/write
X-Memnex-API-Key: mx_live_kXXXX_<secret>
Content-Type: application/json

{
  "user_id": "u_123",
  "channel": "voice",
  "facts": [
    {
      "fact": "Order #4521 arrived damaged",
      "type": "issue",
      "entities": ["order:4521"],
      "confidence": 0.95
    },
    {
      "fact": "Wants a refund",
      "type": "intent",
      "entities": ["order:4521"],
      "confidence": 0.9
    }
  ]
}
```

The fact shape is the same as the MCP tool — see [mcp.md](mcp.md#tools) for the full Pydantic-validated schema.

---

## Python embedded (operator / contributor only)

> Tenants integrating with hosted Memnex SaaS should use **MCP** or **REST**, not this. The Python class talks directly to the engine and assumes you control the storage backends.

This is for two cases:
- **Operators** running a self-hosted Memnex who want to call the engine from a Python service in the same process (saves an MCP round-trip).
- **Contributors** writing tests against the in-memory backends.

```python
from memnex import Memnex, MemnexConfig

# In-process engine. tenant_id here is operator-chosen, not a customer-facing
# concept — in production Memnex resolves it from API keys for you.
mx = await Memnex.create(config=MemnexConfig(
    tenant_id="t_internal",            # operator picks this
    postgres_url="postgresql://...",   # leave unset for in-memory (tests only)
    redis_url="redis://...",
    qdrant_url="http://localhost:6333",
    google_api_key="...",
))

# write structured facts
await mx.user_write(
    user_id="u_123",
    channel="voice",
    facts=[
        {"fact": "Order #4521 arrived damaged",
         "type": "issue",
         "entities": ["order:4521"]},
        {"fact": "Wants a refund",
         "type": "intent",
         "entities": ["order:4521"]},
    ],
)

# read
ctx = await mx.user_read(
    user_id="u_123",
    channel="whatsapp",
    target_format="whatsapp",
    token_budget=2000,
)

# search
results = await mx.user_search(
    user_id="u_123",
    query="billing issue",
    max_results=5,
)

# GDPR
receipt = await mx.user_forget(user_id="u_123", reason="gdpr_request")

# admin
stats = await mx.stats()

await mx.close()
```

For the full operator workflow including how to wire this into FastAPI / a worker / a background job, see [operator-guide.md](operator-guide.md).

---

## CLI (operator only)

```bash
# Server
memnex serve mcp  --transport stdio
memnex serve mcp  --transport streamable-http --host 0.0.0.0 --port 8500
memnex serve rest --host 0.0.0.0 --port 8500

# Database
memnex db init      # create tables, RLS policies, indexes
memnex db migrate   # idempotent
memnex db vacuum    # expire TTL'd memories

# Identity admin
memnex identity resolve --channel voice --id "+91..."
memnex identity link    --from "voice:+91..." --to "web:sess_..."
memnex identity graph   --customer cust_...

# Customer-data admin (operator-side; tenants do this via REST/MCP)
memnex stats
memnex export --customer cust_...
memnex forget --customer cust_... --reason gdpr_request

# Eval / benchmarks
memnex eval --suite full
memnex eval --suite load_test --agents 10000
```

The single recommended way to launch the MCP server in production is `memnex serve mcp --transport streamable-http`. For local development against Claude Desktop, use `--transport stdio` with `MEMNEX_DEV_KEY=1` (which auto-creates a throwaway tenant + API key on boot).
