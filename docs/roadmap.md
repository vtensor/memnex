# Roadmap

Honest priorities, in three tiers. Tier 1 unblocks the next release; Tier 2 is the differentiator that justifies the price tag; Tier 3 is enterprise polish.

## Tier 1 — retrieval quality (next release)

These are table-stakes for "memory that works." Plain vector top-k against an LLM-quality embedder gets you 70% of the way; the gaps below are most of the remaining 30%.

### 1. Hybrid search (BM25 + vector + RRF fusion)
**Why.** Pure-vector retrieval misses exact matches like order IDs (`#4521`), SKUs, emails. BM25 catches them. Reciprocal Rank Fusion combines the two without tuning weights.
**Where.** New `HybridRetriever` in `src/memnex/memory/retrieval.py`, called from `MemoryManager.search`.
**Cost.** Postgres has built-in `tsvector` for BM25; no new infra.

### 2. Cross-encoder reranker on top-k
**Why.** Bi-encoder retrieval (what we use today) is fast but imprecise. A cross-encoder reranker on the top-50 boosts recall@5 by 20–40% on standard benchmarks. Cohere Rerank or `bge-reranker-v2-m3` run locally are both viable.
**Where.** New `Reranker` protocol; called between vector search and the salience compressor.
**Cost.** ~50ms per query if local; ~100ms via API.

### 3. Temporal decay at read time
**Why.** Today, salience is frozen at write time. A 6-month-old "I love pizza" can outrank yesterday's "I'm vegan now." A simple time-decay multiplier at retrieval fixes it.
**Where.** `Compressor` in `src/memnex/memory/compressor.py`.

## Tier 2 — the memory differentiator

These move us from "RAG with a nice schema" to "actual memory product."

### 4. LLM-based fact merging
**Why.** Today, conflict detection supersedes the older fact (`is_active=False`). Better: merge into one fact with a history trail (`status: cancel_requested → cancel_rescinded [2026-04-25]`). This is what makes "memory" feel like memory.
**Where.** `MemoryManager._resolve_conflict` becomes pluggable; ship a default LLM merger and a deterministic fallback.

### 5. Entity resolution and canonicalization
**Why.** "order XYZ", "#XYZ", "the XYZ one" should collapse to the same entity. Today they're three separate strings, so conflict detection misfires.
**Where.** New `EntityResolver` invoked at write time; uses tenant-scoped alias maps.

### 6. Postgres-backed `TenantStore`
**Why.** Today's `TenantStore` is in-memory only. Production SaaS needs durability across restarts and replicas. Single-class swap behind the existing protocol.
**Where.** `src/memnex/saas/postgres_store.py`. Hooked in via `bootstrap_store_from_env`.

### 7. Eval harness — LongMemEval and LOCOMO scores
**Why.** "Memnex is good" is a marketing claim. "Memnex scores X on LongMemEval" is a number. Enterprise buyers want numbers.
**Where.** Extend `src/memnex/eval/suites/` with the public benchmark datasets; publish per-release.

## Tier 3 — enterprise and polish

### 8. Memory graph
**Why.** Entities as nodes, facts as edges. Enables "tell me everything about order XYZ" without relying on embedding luck. Also useful for household / org-level memory ("Vikram is Priya's son — they share an address").

### 9. Per-tenant rate limits and usage quotas
**Why.** Required for any paid tier. Today there are no enforced caps beyond the request-level size limits.

### 10. Channel-aware merging
**Why.** Voice + explicit confirmation should outweigh ambient WhatsApp chatter. Today merging is purely temporal.

### 11. HTTP MCP transport tested end-to-end
**Why.** Today integration tests drive the tool handlers directly. The HTTP transport itself isn't covered.

### 12. Observability — retrieval traces, recall@k per query, salience drift
**Why.** Operators need to see *why* a retrieval missed. Today the metrics are surface-level (counts, latencies).

## Out of scope (intentionally)

- A built-in chatbot UI. Memnex is infra; bring your own agent.
- A built-in CRM. Stores agent-relevant facts, not your sales pipeline.
- Real-time pub-sub of memory changes. Polling is sufficient for the use cases we serve.
- Multi-modal memory (image / doc references). Possible later, not soon.
