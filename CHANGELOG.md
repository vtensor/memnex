# Changelog

All notable changes to Memnex are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.1] - 2026-04-26

### Fixed
- README links now use absolute GitHub URLs so they resolve correctly on the PyPI project page (relative links 404 outside the GitHub tree).
- Removed em-dashes throughout the README for consistent typography.

### Changed
- Trimmed the README: moved the "What's tested" status section and the roadmap into `docs/` where they belong; the README links to them instead of duplicating content.

## [0.1.0] - 2026-04-25

Initial public release.

### Added — MCP server
- 5 tools: `memory_write`, `memory_read`, `memory_search`, `memory_forget`, `memory_trace`
- 3 resources: `memnex://schema/fact-types`, `memnex://users/{user_id}/memories`, `memnex://tenants/me/stats`
- 3 prompts: `memory-writer`, `memory-reader`, `hallucination-check`
- Two transports: `stdio` (local subprocess) and `streamable-http` (hosted)
- Pydantic-validated structured fact input on `memory_write`; no LLM on the hot path

### Added — Multi-tenant SaaS
- Tenant register / login with PBKDF2-SHA256 hashing
- API keys in `mx_live_kXXXX_<secret>` format with HMAC verification
- JWT-based dashboard sessions
- REST endpoints for key creation / listing / revocation
- `MEMNEX_DEV_KEY=1` dev convenience that bootstraps a throwaway local tenant

### Added — Memory engine
- Cross-channel write / read / search across voice, WhatsApp, web, SMS, app
- Channel-aware output formatting (voice gets terse bullets; web gets markdown)
- 5-type fact taxonomy: intent, preference, profile, issue, resolution
- Salience scoring (specificity, actionability, recency, emotion, uniqueness)
- Token-budget-aware compression with type-pinning
- Conflict detection (entity overlap + polarity flip) with three resolution strategies
- Background compaction worker with Jaccard-based dedup

### Added — Privacy & compliance
- Regex-based PII detection for regulated identifiers (Aadhaar, PAN, credit card, IBAN, SSN, bank account, email, phone, OTP)
- Optional Presidio second layer (gated to regulated entities only — names, addresses, order IDs are never masked)
- Three masking strategies: `hash` (default; same value → same token), `redact`, `encrypt`
- GDPR `forget` purges Redis + Postgres + Qdrant + pending Kafka events for the customer
- Signed audit receipts via HMAC; tamper-evident even without a key

### Added — Storage
- Pluggable backends via `HotStore` / `WarmStore` / `SemanticStore` protocols
- In-memory backend for tests and local dev
- Postgres warm store with row-level security
- Redis hot store
- Qdrant semantic store with cosine similarity

### Added — Embeddings
- Default: Google Generative AI (`models/text-embedding-004`, 768 dim) via LangChain
- Optional: OpenAI (`text-embedding-3-small`)
- Hash-based fallback for tests / when no API key is configured

### Added — Observability
- Optional Prometheus metrics
- Grafana dashboard JSON (`grafana/dashboards/memnex_overview.json`)

### Added — Eval
- 6 benchmark suites: recall, conflict, injection-deep, provenance, audit, chaos
- Reports written to `tests/reports/`

### Tested
- 155 unit + integration tests (in-memory backends)
- 17 prompt-injection scenarios blocked at the MCP boundary
- 24 provenance / trust-policy assertions
- Multi-tenant isolation verified across storage, MCP, and SaaS layers
