# Operator guide (for self-hosters)

This is the guide for **someone running Memnex itself** — either as the sole operator of their own instance, or as the owner of the hosted service. If you're integrating an AI agent with an existing Memnex instance, see [integration-guide.md](integration-guide.md) instead.

There are three paths an operator can take. Pick one.

| Path | When to pick it |
|---|---|
| **A. `memnex serve` as a process** | You want a separate memory service that multiple agents reach over MCP or REST. The default. |
| **B. Embed Memnex in your own Python app** | Your backend is already Python and you want zero network hop between your code and the memory engine. |
| **C. Just for tests / local dev** | You're contributing to Memnex itself, or running a 5-minute demo. |

---

## Path A — Run Memnex as a server (recommended)

This is what production looks like.

### A.1 — Bring up the storage backends

```bash
docker compose up -d postgres redis qdrant
```

The included [docker-compose.yml](../docker-compose.yml) brings up Postgres, Redis, Qdrant, and Memnex itself with healthchecks. To bring up only the databases (e.g. when running tests against real backends), `docker compose up -d postgres redis qdrant` skips the Memnex container.

### A.2 — Set the operator's env vars

Copy `.env.example` to `.env` and fill in the **server-side** section. **Do not put any of these in an agent / MCP-client config** — they are infrastructure secrets.

```bash
MEMNEX_POSTGRES_URL=postgresql://memnex:memnex@localhost:5432/memnex
MEMNEX_REDIS_URL=redis://localhost:6379/0
MEMNEX_QDRANT_URL=http://localhost:6333
GOOGLE_API_KEY=AIza...                   # for embeddings
MEMNEX_AUDIT_KEY=$(openssl rand -hex 32) # signs audit receipts
MEMNEX_JWT_SIGNING_KEY=$(openssl rand -hex 32)  # SaaS dashboard JWTs
```

### A.3 — Initialize the database

```bash
memnex db init
# creates tables, RLS policies, indexes
```

This is idempotent — `memnex db migrate` runs the same path. Re-run after upgrades.

### A.4 — Issue an API key for your first tenant

In production, tenants self-serve via the dashboard (`memnex serve rest` exposes register/login at `/api/v1/auth/*`). For a quick start without the dashboard, do it from Python:

```python
import asyncio
from memnex.saas.accounts import TenantStore

async def issue():
    store = TenantStore()
    tenant = store.register("you@yourcompany.com", "your-strong-password")
    raw_key, _meta = store.add_key(tenant.tenant_id, label="first-key")
    print(f"Tenant: {tenant.tenant_id}")
    print(f"API key: {raw_key}")

asyncio.run(issue())
```

> The current `TenantStore` is in-memory only. For production durability across restarts, the [Postgres-backed `TenantStore`](roadmap.md) is on the Tier-2 roadmap. If you're shipping today, hold tenants in your own auth system and only issue API keys at deploy time.

### A.5 — Start the server

```bash
# stdio (for Claude Desktop subprocess use)
memnex serve mcp --transport stdio

# streamable-http (for a real network endpoint)
memnex serve mcp --transport streamable-http --host 0.0.0.0 --port 8500

# REST API + dashboard
memnex serve rest --host 0.0.0.0 --port 8500
```

Hand the API key to your tenants. They follow [integration-guide.md](integration-guide.md) from there.

### A.6 — Local dev shortcut

Skip A.4 entirely with:

```bash
MEMNEX_DEV_KEY=1 memnex serve mcp --transport stdio
# stderr: [memnex] MEMNEX_SECRET_KEY=mx_live_kXXXX_<secret>
```

This auto-creates a throwaway tenant and prints a single-use API key. **Never set `MEMNEX_DEV_KEY` in production** — it skips the password / payment / contract flow.

---

## Path B — Embed Memnex in your Python app

Use this when:

- Your backend is already Python and adding an MCP / REST hop is unnecessary overhead.
- You want to extend the engine — custom embedder, custom salience scoring, custom storage.
- You need data sovereignty / air-gap and aren't comfortable depending on a hosted memory service.

### B.1 — Install

```bash
pip install 'memnex[postgres,redis,qdrant,embeddings-google]'
```

The optional extras pull in the storage drivers and Google's embedding client. Skip them and Memnex falls back to in-memory backends + a hash embedder, which is **only suitable for tests**.

### B.2 — Construct the client

```python
import asyncio
from memnex import Memnex, MemnexConfig

async def setup():
    mx = await Memnex.create(config=MemnexConfig(
        tenant_id="t_internal",                       # you pick — opaque label
        postgres_url="postgresql://...",
        redis_url="redis://...",
        qdrant_url="http://localhost:6333",
        google_api_key="AIza...",
    ))
    return mx
```

> `tenant_id` here is **operator-chosen**. In a multi-tenant deployment you'd derive it from your auth system (e.g. one Memnex tenant per workspace). It's not a customer-facing concept — your end users never see or supply it.

### B.3 — Use it

```python
mx = await setup()

# Write structured facts (recommended — no LLM, no surprises)
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

# Read formatted context (channel-aware)
context = await mx.user_read(
    user_id="u_123",
    channel="whatsapp",
    target_format="whatsapp",
    token_budget=1500,
)

# Search a single user's memories
results = await mx.user_search(
    user_id="u_123",
    query="refund",
    max_results=5,
)

# Trace a draft reply against memory (hallucination check)
hits = await mx.user_trace(
    user_id="u_123",
    agent_output="Your order #4521 was refunded last Tuesday.",
)

# GDPR forget
receipt = await mx.user_forget(user_id="u_123", reason="gdpr_request")

# Per-tenant stats
stats = await mx.stats()

await mx.close()
```

### B.4 — When you also want to expose Memnex to other agents

Path B isn't mutually exclusive with Path A. You can `import memnex` in your Python app **and** run `memnex serve mcp` to give external agents access to the same memory pool. Both paths talk to the same Postgres / Redis / Qdrant.

---

## Path C — Tests and local dev

For unit tests, demos, or hacking on Memnex itself.

```python
from memnex import Memnex, MemnexConfig

# All in-memory. No Postgres, no Redis, no API keys.
mx = await Memnex.create(config=MemnexConfig(tenant_id="t_test"))
```

This runs the full engine against in-memory backends and a hash-based embedder. Retrieval is structurally correct but semantically near-random — **not for production**.

The `tests/` directory exercises this configuration with 177 passing tests in under a second.

---

## Operational concerns

### Database migrations

```bash
memnex db init      # first-time setup; idempotent
memnex db migrate   # alias for init
memnex db vacuum    # remove TTL'd memories
```

Migrations live in [src/memnex/storage/migrations/](../src/memnex/storage/migrations/). They are SQL files run in alphabetical order. RLS policies are applied as part of `001_rls_policies.sql`.

### Backup

- **Postgres**: nightly `pg_dump` is fine. Memory facts are durable here.
- **Qdrant**: snapshot the storage volume. Embeddings can be regenerated from Postgres if lost (slow but possible — facts → re-embed → re-upsert).
- **Redis**: not durable by design. It's a hot cache; losing it is fine.

### Audit and compliance

Every write produces an HMAC-signed receipt. Verify them with:

```python
from memnex.audit.receipts import verify_receipt
ok = verify_receipt(receipt, key=os.environ["MEMNEX_AUDIT_KEY"])
```

Receipts chain by sequence number, so tampering with one breaks all subsequent ones. Useful for proving to a regulator that a forget actually happened.

### Metrics

Prometheus metrics are exposed at `GET /metrics` when `enable_metrics=True` in config (default). Scrape from your Prometheus instance and graph in Grafana — we don't ship dashboards (operator-internal concern).

### Scaling

- The MCP / REST server is stateless. Run multiple replicas behind a load balancer.
- Postgres takes the brunt of write traffic; use connection pooling (PgBouncer).
- Redis is a single-node cache. Replicate or shard if you need multi-region.
- Qdrant scales horizontally — consult Qdrant's docs.

The version-clock + invalidation-bus design ([src/memnex/concurrency/](../src/memnex/concurrency/)) is built for multi-replica deployments. Replicas exchange invalidation events over the bus so a write on replica A immediately invalidates the cache on replica B.

---

## Upgrading

```bash
pip install --upgrade memnex
memnex db migrate
```

Migrations are idempotent and forward-only. Read [CHANGELOG.md](../CHANGELOG.md) before upgrading across a minor version — breaking changes are flagged there.

---

## Next reading

- [architecture.md](architecture.md) — the four invariants and where each lives in the code
- [security.md](security.md) — multi-tenant isolation, audit ledger, regulated PII
- [deployment.md](deployment.md) — Docker, scaling, env vars
- [api-reference.md](api-reference.md) — full Python / REST surface
- [eval.md](eval.md) — the 6 benchmark suites for QA
