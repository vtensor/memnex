# 03 — System design

## Components

| Component | File | Responsibility |
|---|---|---|
| `Memnex` | [client.py](../src/memnex/client.py) | Public facade |
| `IdentityResolver` | [identity/resolver.py](../src/memnex/identity/resolver.py) | Resolve, link, check match |
| `MemoryManager` | [memory/manager.py](../src/memnex/memory/manager.py) | Write, read, search |
| `Extractor` | [memory/extractor.py](../src/memnex/memory/extractor.py) | Rule-based + LLM fact extraction |
| `SalienceScorer` | [memory/salience.py](../src/memnex/memory/salience.py) | 0.0–1.0 scoring |
| `ConflictResolver` | [memory/conflict.py](../src/memnex/memory/conflict.py) | Detect & resolve contradictions |
| `Compressor` | [memory/compressor.py](../src/memnex/memory/compressor.py) | Fit into token budget |
| `ChannelAdapter` | [channels/](../src/memnex/channels/) | Extract + format per channel |
| `GDPRCoordinator` | [privacy/gdpr.py](../src/memnex/privacy/gdpr.py) | Forget + export |
| `PIIMasker` | [privacy/masker.py](../src/memnex/privacy/masker.py) | Mask at write |
| `Workers` | [workers/](../src/memnex/workers/) | Compaction, merges, TTL |

## Storage tiers

```
┌──────────────────────────────────────────────────────────────┐
│  HOT — Redis / in-memory                                     │
│    working_memory per customer      (last N facts)           │
│    identifier_cache                 (channel,id → customer)  │
│    TTL: 24h (configurable)                                   │
├──────────────────────────────────────────────────────────────┤
│  WARM — Postgres / in-memory                                 │
│    customer_identities              (root)                   │
│    channel_identifiers              (one → many)             │
│    memories                         (facts with metadata)    │
│    candidate_links                  (unconfirmed fuzzy)      │
│    Retention: per-tenant policy                              │
├──────────────────────────────────────────────────────────────┤
│  SEMANTIC — Qdrant / in-memory                               │
│    one collection per tenant                                 │
│    vector + {customer_id, fact_type, channel, salience}      │
└──────────────────────────────────────────────────────────────┘
```

## Data flow

```
agent ──┐
        │ SDK / REST / MCP
        ▼
   ┌─────────────┐
   │  Memnex     │
   │   ├── IdentityResolver ─→ hot + warm
   │   ├── MemoryManager    ─→ hot + warm + semantic
   │   ├── ChannelAdapter   ─→ in-process
   │   └── GDPRCoordinator  ─→ hot + warm + semantic
   └─────────────┘
        │
        ▼
   workers (compaction, identity merge, TTL) — optional
```

## Why three tiers

- **Hot**: sub-5 ms reads for active sessions. Redis is the default; in-memory works for tests.
- **Warm**: durable, queryable, RLS-protected. Postgres JSONB covers 90% of queries; indexes cover the rest.
- **Semantic**: Qdrant handles similarity search only. Kept optional — many deployments don't need it.

## Pluggability

Storage is behind `HotStore`, `WarmStore`, `SemanticStore` protocols ([storage/base.py](../src/memnex/storage/base.py)). The in-memory default means tests run with zero dependencies and production swaps in the real backends by setting env vars.

## Async-first

Everything is `async`. No blocking calls on the request path. FastAPI, asyncpg, redis-async, qdrant async client.

## Scale notes

| Dimension | Strategy |
|---|---|
| Concurrent agents | Async I/O + connection pools (asyncpg, redis) |
| Multi-tenant fairness | Per-tenant rate limiter (Redis-backed in prod) |
| Cold reads | Working-memory cache warms on first hit |
| Multi-instance cache | Redis PUBSUB invalidation (auto when `MEMNEX_REDIS_URL` set) |
| Bulk writes | `max_facts_per_write` cap + salience drop |
