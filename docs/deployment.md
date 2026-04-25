# 06 — Deployment

## Local, zero dependencies

```python
from memnex import Memnex
mx = await Memnex.create(tenant_id="demo")
```

Uses in-memory backends. Great for tests, scripts, notebooks.

## Local stack (Docker)

```bash
docker compose up -d postgres redis qdrant      # backends only
export MEMNEX_POSTGRES_URL=postgresql://memnex:memnex@localhost:5432/memnex
export MEMNEX_REDIS_URL=redis://localhost:6379/0
export MEMNEX_QDRANT_URL=http://localhost:6333
export GOOGLE_API_KEY=...
memnex db init
memnex serve rest --port 8500
```

For the full stack (databases + the Memnex container itself), `docker compose up -d`.

## Production checklist

| | |
|---|---|
| **Compute** | Any container runtime. CPU-bound (minus DB). 1-2 vCPU per instance typical |
| **Postgres** | 15+, `pgcrypto` enabled, RLS on, backups daily, connection pooler (PgBouncer) |
| **Redis** | 7+, AOF persistence if you want warm caches across restarts, ACLs per tenant |
| **Qdrant** | Optional; one collection per tenant (default) |
| **Auth** | Set `MEMNEX_API_KEYS`. Front with a gateway for TLS |
| **Rate limit** | Swap the in-memory limiter for a Redis-backed one at scale |
| **Observability** | Scrape `/api/v1/metrics`. Dashboard in `grafana/dashboards/` |
| **Workers** | Run compaction + privacy workers separately from the API |

## Environment variables

| Var | Purpose |
|---|---|
| `MEMNEX_TENANT_ID` | Default tenant for this process |
| `MEMNEX_POSTGRES_URL` | `postgresql://...` |
| `MEMNEX_REDIS_URL` | `redis://...` |
| `MEMNEX_QDRANT_URL` | `http://...` |
| `MEMNEX_KAFKA_BROKERS` | Optional, for event streaming |
| `MEMNEX_LLM_PROVIDER` | `openai` / `anthropic` / `ollama` / `none` |
| `MEMNEX_LLM_MODEL` | Model name |
| `MEMNEX_LLM_API_KEY` | Provider key |
| `MEMNEX_API_KEYS` | `key1:tenant1,key2:tenant2` |

## Scaling roadmap

| Load | Change |
|---|---|
| < 1k QPS | Single process. In-memory limiter is fine |
| 1k–10k QPS | Horizontal scale API. Move limiter to Redis. Enable Qdrant |
| > 10k QPS | Read replicas for Postgres. Shard by tenant across Postgres + Redis. |

## Upgrade strategy

- SQL migrations are idempotent; re-running `memnex db init` is safe.
- Config is a Pydantic model; new fields default safely.
- In-place rolling restarts work — no sticky state on any instance.
