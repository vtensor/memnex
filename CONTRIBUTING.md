# Contributing to Memnex

Thanks for considering a contribution. This document explains the dev
loop, the conventions, and what we look for in a PR.

## Quick dev setup

```bash
git clone https://github.com/vtensor/memnex.git
cd memnex
python -m venv .venv && source .venv/bin/activate
pip install -e '.[dev,all]'
pytest -q
```

All 155+ tests should pass against the in-memory backends. No Postgres,
Redis, Qdrant, or API keys are required for the default test suite.

## Project layout

```
src/memnex/         # library + server code (PEP 621 src layout)
  api/              # FastAPI REST surface
  audit/            # signed write receipts, trace
  channels/         # voice / WhatsApp / web / SMS / app adapters
  cli/              # `memnex` Click CLI
  concurrency/      # version clocks, ledger, invalidation bus
  eval/             # benchmark suites
  identity/         # phone normalization, identity resolution
  mcp/              # MCP server (tools, resources, prompts)
  memory/           # write/read/search/conflict/extraction
  privacy/          # PII detection, GDPR purge, TTL
  provenance/       # trust policy, injection filter
  saas/             # tenant accounts, API keys, dashboard routes
  storage/          # pluggable backends + migrations
  workers/          # background compaction, identity merge
tests/              # unit + integration
docs/               # markdown documentation
examples/           # integration demos
```

We use the `src/` layout intentionally — it prevents accidental local
imports during development and matches the modern PyPA recommendation.
Don't flatten it.

## Running checks

```bash
pytest -q                    # all tests
ruff check .                 # lint
ruff format .                # format
mypy src                     # type check (strict mode)
```

## Commit and PR conventions

- One logical change per PR. Keep diffs surgical.
- Update [CHANGELOG.md](CHANGELOG.md) for user-visible changes.
- Add or update tests for any code change. Bug fixes should ship with a
  test that fails without the fix and passes with it.
- Update relevant docs in `docs/` if you change behavior.
- If your change touches the MCP surface (tools, resources, prompts),
  update `docs/mcp.md` and the README's MCP section.

## Architectural invariants

These are the guardrails. Breaking any of them needs an explicit design
discussion in the PR.

1. **Multi-tenant isolation is non-negotiable.** Every memory or identity
   query must be scoped by `tenant_id`. Postgres RLS is the safety net,
   not the primary guard.
2. **PII masking happens at write time, not read time.** Once PII is in
   plaintext storage, a future bug can leak it. The write path is the
   chokepoint.
3. **Storage backends are pluggable.** Core code talks to `HotStore`,
   `WarmStore`, `SemanticStore` protocols — never to Redis/Postgres/Qdrant
   directly. This keeps tests fast and backends swappable.
4. **Async-first.** All I/O is `async`. No blocking calls in request paths.
5. **No global state.** Configuration flows through `MemnexConfig`, not
   module-level globals.
6. **Server-side vs client-side env vars are distinct.** Anything in
   `server_config.ServerInfra` (Postgres URL, Google API key, audit key,
   JWT key) is operator-only. Tenants only ever see `MEMNEX_SECRET_KEY`
   and `MEMNEX_CHANNEL`. Never blur this line in docs or examples.

## What not to do

- Don't add logging that prints memory content — memories contain PII.
- Don't silently catch exceptions in the storage layer — let them
  propagate so the caller can decide.
- Don't create new abstractions until there's a second concrete use case.
- Don't add features beyond what an issue or PR description asks for.

## Reporting bugs

Use the issue templates in `.github/ISSUE_TEMPLATE/`. For security issues,
follow [SECURITY.md](SECURITY.md) — do not file a public issue.

## License

By contributing, you agree your contributions will be licensed under the
[Apache License 2.0](LICENSE).
