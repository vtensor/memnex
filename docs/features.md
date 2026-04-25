# Features

What's built today, what's on the roadmap, and what's intentionally out of scope.

## Built and shipping in v0.1.0

### MCP server
- 5 tools: `memory_write`, `memory_read`, `memory_search`, `memory_forget`, `memory_trace`
- 3 resources: `memnex://schema/fact-types`, `memnex://users/{user_id}/memories`, `memnex://tenants/me/stats`
- 3 prompts: `memory-writer`, `memory-reader`, `hallucination-check`
- Two transports: `stdio` (local subprocess) and `streamable-http` (hosted)
- Pydantic-validated structured fact input — no generative LLM on the hot path

### Multi-tenant SaaS
- Tenant register / login (PBKDF2-SHA256, 200k iterations)
- API keys: `mx_live_kXXXX_<secret>`, HMAC-verified, scoped to one tenant
- JWT-based dashboard sessions
- REST endpoints for key creation / listing / revocation
- `MEMNEX_DEV_KEY=1` convenience for local dev (auto-creates a throwaway tenant)

### Memory engine
- Cross-channel write / read / search across voice, WhatsApp, web, SMS, app
- Channel-aware output formatting (voice gets terse bullets; web gets markdown)
- 5-type fact taxonomy: intent, preference, profile, issue, resolution
- Salience scoring (specificity, actionability, recency, emotion, uniqueness)
- Token-budget-aware compression with type-pinning
- Conflict detection (entity overlap + polarity flip) with three strategies (`latest_wins`, `keep_both`, `ask_agent`)
- Background compaction worker with Jaccard-based dedup

### Privacy and compliance
- Regex-based PII detection for regulated identifiers: Aadhaar, PAN, credit card, IBAN, SSN, bank account, email, phone, OTP
- Optional Presidio second layer (gated to regulated entities only — names, addresses, order IDs are never masked)
- Three masking strategies: `hash` (default; same value → same token), `redact`, `encrypt`
- GDPR `forget` purges Redis + Postgres + Qdrant + pending Kafka events
- Signed audit receipts (HMAC); tamper-evident even without a key

### Storage
- Pluggable backends via `HotStore` / `WarmStore` / `SemanticStore` protocols
- In-memory backend for tests and local dev
- Postgres warm store with row-level security
- Redis hot store
- Qdrant semantic store with cosine similarity

### Embeddings
- Default: Google Generative AI (`models/text-embedding-004`, 768 dim) via LangChain
- Optional: OpenAI (`text-embedding-3-small`)
- Hash fallback for tests / when no API key is configured

### Identity
- Phone normalization via `phonenumbers` (E.164)
- WhatsApp / email / web / app identifier normalization
- Fuzzy identity candidates with confidence scoring (no auto-merge)

### Observability
- Optional Prometheus metrics
- Per-tenant counts, latencies, attack-block rates

### Eval
- 6 benchmark suites: recall, conflict, injection-deep, provenance, audit, chaos
- Reports written to `tests/reports/`

## Planned (see [roadmap.md](roadmap.md))

- Hybrid search (BM25 + vector + RRF fusion)
- Cross-encoder reranker on top-k retrievals
- LLM-based fact merging (history trail instead of pure supersession)
- Entity resolution and canonicalization
- Postgres-backed `TenantStore` (replaces in-memory store for production)
- LongMemEval / LOCOMO benchmark scores published per release
- Memory graph (entities as nodes, facts as edges)
- Per-tenant rate limits and usage quotas

## Intentionally out of scope

- **Conversation buffer / scrollback memory.** That's the agent's job. Memnex stores durable facts, not turn history.
- **Vendor-specific workflow templates** (e.g. "how Zendesk support agents should triage"). That belongs in the host application.
- **Real-time live streams of memory changes.** Memory changes constantly; subscriptions are expensive. Use tools + polling.
- **Storing PII as plaintext.** Regulated identifiers are masked at write time. Names and addresses are stored because the product needs them, but compliance is via tenant isolation and encryption at rest, not masking.
