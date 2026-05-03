<p align="center">
  <img src="docs/assets/memnex.png" alt="Memnex — cross-channel permanent memory for AI agents" width="600">
</p>

**Cross-channel permanent memory for AI agents**

Memnex is a memory service for conversational AI agents. When the same user moves from a phone call to WhatsApp to web chat, every agent on every channel already knows what happened on the previous channels: same name, same open issues, same preferences, same history. No more "how can I help you today?" on channel three.

It plugs in over the **Model Context Protocol** (MCP), so any MCP-compatible agent (Claude Desktop, Cursor, LangGraph, CrewAI, your own runtime) can use it without writing integration code.

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://github.com/vtensor/memnex/blob/main/LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)

---

## Why this exists

Most agent platforms have *short-term* conversation memory (the chat scrollback). They don't have *long-term, cross-channel* memory. So a customer who calls support on Monday and messages on Wednesday talks to two strangers, even when both are powered by the same LLM. They re-explain everything. Trust evaporates.

Memnex fixes this by being a **shared memory layer** the agents talk to. Each agent writes durable facts as the conversation unfolds (intent, preferences, issues, resolutions, profile attributes), and reads them back at the start of every turn. When channels hand off, nothing is lost. When a session disconnects mid-flow, only the un-written facts are lost. Write per sub-intent and even that goes away.

---

## Quick start

### As an MCP server (recommended for agent runtimes)

Memnex is open-source and self-hosted. Run the server yourself (your machine, your cloud, Railway, Fly.io, AWS, GCP, anywhere a Python process can run); your agents connect to it over MCP.

```bash
pip install memnex
export GOOGLE_API_KEY=...                  # for embeddings
export MEMNEX_POSTGRES_URL=postgres://...  # or leave unset for in-memory (dev only)
export MEMNEX_DEV_KEY=1                    # auto-creates a dev API key on boot
memnex serve mcp --transport stdio
# stderr: [memnex] MEMNEX_SECRET_KEY=mx_live_k.....
```

Take the printed key and put it in your MCP client config:

```jsonc
{
  "mcpServers": {
    "memnex": {
      "command": "memnex",
      "args": ["serve", "mcp", "--transport", "stdio"],
      "env": {
        "MEMNEX_SECRET_KEY": "mx_live_kXXXXXXXX_<secret>",
        "MEMNEX_CHANNEL": "voice"
      }
    }
  }
}
```

For a real network endpoint instead of a stdio subprocess, run `memnex serve mcp --transport streamable-http --port 8500` and point your client at `http://your-host:8500/mcp` with the same API key in headers.

> **Common deployment mistake:** putting `GOOGLE_API_KEY` or `MEMNEX_POSTGRES_URL` in the client `env` block. Those are *server-side* infrastructure secrets. Set them where the server runs, never in the agent's MCP config. The client only ever needs `MEMNEX_SECRET_KEY` and `MEMNEX_CHANNEL`. See [Configuration](#configuration) for the full split.

> **Tenants integrate via MCP, not by importing Memnex into Python.** The Python codebase is what runs on the server. Self-hosters and contributors may run it directly. See the [operator guide](https://github.com/vtensor/memnex/blob/main/docs/operator-guide.md) for that path.

---

## What the MCP server exposes

Three primitives: **Tools** (functions the agent calls), **Resources** (read-only data the host app fetches), **Prompts** (reusable templates the host can pull).

### Tools (5)

| Tool | Purpose |
|---|---|
| `memory_write` | Store one or more structured facts about the user. Pydantic-validated. No LLM on the hot path. |
| `memory_read` | Fetch formatted memory context for one user, sized to a token budget. |
| `memory_search` | Semantic search over a single user's memories. |
| `memory_forget` | GDPR purge. Wipes Redis, Postgres, Qdrant, and pending events for the user. |
| `memory_trace` | Given a draft agent reply, return the source memories that could have produced it. Empty hits suggests a hallucination. |

Example call:

```jsonc
{
  "tool": "memory_write",
  "arguments": {
    "user_id": "u_123",
    "facts": [
      {
        "fact": "Wants to cancel order XYZ",
        "type": "intent",
        "entities": ["order:XYZ"],
        "confidence": 0.95
      }
    ]
  }
}
```

### Resources (3)

| URI | Returns | When to read |
|---|---|---|
| `memnex://schema/fact-types` | Markdown describing the 5 fact types with examples and the `entities` "type:value" convention | Once at agent startup, so the host LLM learns the taxonomy |
| `memnex://users/{user_id}/memories` | JSON of all active memories for one user (tenant-scoped) | When you want to render a "what we remember" panel in your support UI |
| `memnex://tenants/me/stats` | JSON with per-tenant counts and oldest/newest timestamps | Admin dashboard, health check, billing/usage view |

### Prompts (3)

| Name | When to use |
|---|---|
| `memory-writer` | Pull at agent startup as the system-prompt section that teaches the LLM **when** to write (per sub-intent, not at end of conversation) and **how** (5 types, entities convention, structured facts over raw text). |
| `memory-reader` | Pull at agent startup to teach the LLM how to call `memory_read` once per turn and where to fold the returned context into its prompt without echoing it verbatim. |
| `hallucination-check` | Pull when you want a verification step. Wraps `memory_trace` so the agent verifies its draft reply against stored facts before sending. |

---

## Architecture

```
                   ┌────────────────┐
   Voice agent ──▶ │                │
                   │                │      Identity ──▶ phone / wa / email / web normalization
WhatsApp agent ──▶ │  MCP / REST /  │ ──▶  Memory   ──▶ extract · score · conflict · compress
                   │   stdio        │      Privacy  ──▶ regex + Presidio · GDPR forget
   Web agent  ──▶  │                │      Audit    ──▶ HMAC-signed write ledger
                   └────────────────┘
                          │
                          ▼
              ┌─────────┬─────────┬─────────┐
              │  Redis  │ Postgres│ Qdrant  │
              │  (hot)  │ (warm,  │(semantic│
              │         │  RLS)   │  vector)│
              └─────────┴─────────┴─────────┘
                          ▲
                          │
                      embeddings
```

All four layers (Identity, Memory, Privacy, Audit) are tenant-scoped. Storage is pluggable behind `HotStore` / `WarmStore` / `SemanticStore` protocols, so the same code runs against in-memory backends in tests and real services in production.

See the [architecture doc](https://github.com/vtensor/memnex/blob/main/docs/architecture.md) for the full design.

---

## Configuration

Two distinct sets of environment variables. Mixing them up is the single most common deployment mistake.

### Server-side (set by whoever runs the Memnex server)

These are infrastructure secrets. They live on the operator's side. **Never** copy these into an MCP client config.

| Variable | Purpose |
|---|---|
| `MEMNEX_POSTGRES_URL` | Warm storage. Leave unset for in-memory. |
| `MEMNEX_REDIS_URL` | Hot cache. Leave unset for in-memory. |
| `MEMNEX_QDRANT_URL` | Semantic vector store. Leave unset for in-memory. |
| `GOOGLE_API_KEY` | Embeddings (`models/text-embedding-004`). |
| `MEMNEX_AUDIT_KEY` | HMAC key that signs audit receipts. |
| `MEMNEX_JWT_SIGNING_KEY` | Required for the SaaS dashboard register/login flow. |
| `MEMNEX_DEV_KEY` | Set to `1` to auto-create a throwaway dev tenant on `memnex serve mcp` boot. **Never** set in production. |

**Generative LLM (legacy, opt-in):** `MEMNEX_LLM_PROVIDER` and `MEMNEX_LLM_API_KEY` only have an effect if you explicitly switch the provider away from the default `none`. They are used solely by the legacy `raw_text` extraction path; the structured-fact path that all current tools and prompts recommend never invokes a generative LLM. Most operators can leave both unset.

### Client-side (set by the tenant in their MCP client config)

| Variable | Purpose |
|---|---|
| `MEMNEX_SECRET_KEY` | The tenant's API key, in the form `mx_live_kXXXX_<secret>`. |
| `MEMNEX_CHANNEL` | Which channel this agent represents: `voice` / `whatsapp` / `web` / `sms` / `app`. Drives output formatting. |

A copy-paste-ready template is at [.env.example](https://github.com/vtensor/memnex/blob/main/.env.example).

---

## Storage backends

| Layer | Default (no setup) | Production |
|---|---|---|
| Hot (recent reads) | In-memory dict | Redis |
| Warm (durable facts) | In-memory dict | Postgres (with RLS for tenant isolation) |
| Semantic (embeddings) | In-memory list | Qdrant |
| Embeddings model | Hash fallback (testing only) | Google `text-embedding-004` (768 dim) |

All four are gated behind protocol interfaces in [src/memnex/storage/base.py](https://github.com/vtensor/memnex/blob/main/src/memnex/storage/base.py). A new backend is one new class implementing the protocol; no core changes required.

---

## How we compare

Quick orientation. None of these are exact substitutes for each other; pick based on what matters most to you.

| | Memnex | Mem0 | Zep | Letta | OpenAI memory |
|---|---|---|---|---|---|
| Cross-channel by design | ✅ | partial | partial | partial | ❌ |
| Multi-tenant w/ RLS | ✅ | ❌ | ❌ | ❌ | n/a |
| MCP-native | ✅ | ❌ (SDK) | ❌ (SDK) | ❌ (SDK) | ❌ |
| GDPR forget receipts | ✅ signed | ❌ | partial | ❌ | n/a |
| Regulated PII masking at write | ✅ | partial | ❌ | ❌ | n/a |
| Audit ledger (HMAC) | ✅ | ❌ | ❌ | ❌ | ❌ |
| Self-hostable | ✅ | ✅ | ✅ | ✅ | ❌ |

If you want a hosted memory backend bolted to ChatGPT, use OpenAI memory. If you want the smallest possible API for a single-app agent, use Mem0. If you need *cross-channel, multi-tenant, compliance-aware memory exposed over MCP*, that's where Memnex sits.

See the [comparison doc](https://github.com/vtensor/memnex/blob/main/docs/comparison.md) for the longer version.

---

## Documentation

Full documentation lives in the [docs/](https://github.com/vtensor/memnex/tree/main/docs) directory on GitHub. Routed by audience:

- **Integrating an AI agent with Memnex:** [integration guide](https://github.com/vtensor/memnex/blob/main/docs/integration-guide.md)
- **Running Memnex yourself:** [operator guide](https://github.com/vtensor/memnex/blob/main/docs/operator-guide.md)
- **Reference:** [MCP API](https://github.com/vtensor/memnex/blob/main/docs/mcp.md), [REST + Python API](https://github.com/vtensor/memnex/blob/main/docs/api-reference.md), [architecture](https://github.com/vtensor/memnex/blob/main/docs/architecture.md), [security](https://github.com/vtensor/memnex/blob/main/docs/security.md)
- **Status and direction:** [features](https://github.com/vtensor/memnex/blob/main/docs/features.md), [comparison](https://github.com/vtensor/memnex/blob/main/docs/comparison.md), [roadmap](https://github.com/vtensor/memnex/blob/main/docs/roadmap.md)

---

## Contributing

PRs welcome. Read [CONTRIBUTING.md](https://github.com/vtensor/memnex/blob/main/CONTRIBUTING.md) for the dev loop and the architectural invariants we hold to. For security issues, see [SECURITY.md](https://github.com/vtensor/memnex/blob/main/SECURITY.md).

## License

Apache License 2.0. See [LICENSE](https://github.com/vtensor/memnex/blob/main/LICENSE).
