# How Memnex compares

Memory is a crowded space. This page is an honest orientation, not a marketing pitch — pick the tool that fits *your* shape.

## Side-by-side

| | **Memnex** | Mem0 | Zep | Letta (formerly MemGPT) | OpenAI Memory |
|---|---|---|---|---|---|
| **Primary use case** | Cross-channel multi-agent memory for production support / commerce | Per-app memory for a single agent | Per-session and long-term memory for chat agents | Stateful agent runtime with self-managed memory | ChatGPT user-level memory |
| **Cross-channel by design** | ✅ first-class | partial (via `user_id`) | partial | partial | ❌ |
| **Multi-tenant w/ row-level security** | ✅ Postgres RLS | ❌ single-tenant | ❌ single-tenant | ❌ single-tenant | n/a (managed) |
| **MCP-native** | ✅ tools + resources + prompts | ❌ Python/JS SDK | ❌ Python/JS SDK | ❌ Python SDK | ❌ proprietary |
| **GDPR forget** | ✅ signed receipt across all stores | manual delete | partial | manual delete | n/a |
| **Regulated PII masking at write** | ✅ regex + Presidio | partial | ❌ | ❌ | n/a |
| **Audit ledger (HMAC-signed)** | ✅ | ❌ | ❌ | ❌ | ❌ |
| **Storage layer pluggability** | ✅ Redis / Postgres / Qdrant via protocols | hosted-first | hosted-first | LanceDB / Postgres | n/a |
| **Generative LLM on hot path** | ❌ optional | ✅ for fact extraction | ✅ for summarization | ✅ for memory edits | proprietary |
| **Self-hostable** | ✅ Apache-2.0 | ✅ | ✅ | ✅ | ❌ |
| **Conflict detection w/ entity overlap** | ✅ | ❌ | ❌ | ❌ | ❌ |
| **Hallucination trace** | ✅ `memory_trace` | ❌ | ❌ | ❌ | ❌ |
| **Hosted SaaS option** | planned | ✅ | ✅ | ✅ | ✅ |

Last reviewed: 2026-04-25. Some of this changes monthly — check upstream docs before making a procurement decision.

## When to pick what

### Pick Memnex if
- You run **multiple agents on multiple channels** (voice + WhatsApp + web + …) and they need to share state.
- You're a B2B SaaS — multi-tenant isolation is a hard requirement, not a nice-to-have.
- Your customers are in regulated industries (healthcare, finance, India fintech) and ask for audit trails or GDPR-style forget.
- You already use MCP-compatible agent runtimes (Claude Desktop, Cursor, LangGraph) and don't want to write integration code.

### Pick Mem0 if
- You have one agent, one channel, and want the smallest possible API.
- You're early-stage and optimizing for time-to-first-write, not compliance.

### Pick Zep if
- You want session-scoped memory plus longer-term consolidation, baked into a chat-shaped abstraction.
- You're OK with their hosted product as the primary path.

### Pick Letta if
- You want the "agent OS" model where the agent itself manages its memory via tool calls (the MemGPT pattern).
- You want a runtime, not just a memory layer.

### Pick OpenAI Memory if
- You're building inside ChatGPT and want zero infrastructure.
- You don't need cross-tenant isolation (everyone is "your user" via OpenAI account).

## What Memnex is NOT

To save you time:

- **Not a chatbot framework.** Bring your own agent (LangGraph / LangChain / CrewAI / Anthropic SDK / your runtime). Memnex is the memory layer.
- **Not a vector database.** It uses one (Qdrant) under the hood, but the surface is "facts about users", not "vectors and metadata."
- **Not a transcript store.** If you write every conversation turn, retrieval quality collapses. Memnex stores durable facts, not raw history.
- **Not a CRM.** Stores facts the agent needs to do its job, not your sales pipeline.
