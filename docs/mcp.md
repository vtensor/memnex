# MCP API reference

The Memnex MCP server exposes three primitives: **Tools** (functions agents call), **Resources** (read-only data the host app fetches), **Prompts** (reusable templates the host LLM can adopt).

## Connection

Memnex is self-hosted. Two transports are supported.

### stdio subprocess (most portable)

The MCP client launches Memnex as a child process and talks to it over stdin/stdout. Works with Claude Desktop, Cursor, Cline, and any client that supports the standard subprocess MCP pattern.

```jsonc
{
  "mcpServers": {
    "memnex": {
      "command": "memnex",
      "args": ["serve", "mcp", "--transport", "stdio"],
      "env": {
        "MEMNEX_SECRET_KEY": "mx_live_kXXXX_<secret>",
        "MEMNEX_CHANNEL": "voice"
      }
    }
  }
}
```

The operator running this subprocess must export server-side infra (`GOOGLE_API_KEY`, `MEMNEX_POSTGRES_URL`, `MEMNEX_REDIS_URL`, `MEMNEX_QDRANT_URL`, etc.) in the shell that launches the MCP client. These are server-side secrets and **must not** appear in the `env` block above.

### streamable-http (network endpoint)

Run the server as a long-lived HTTP service (`memnex serve mcp --transport streamable-http --port 8500`), and clients reach it over the network with their API key in headers.

```jsonc
{
  "mcpServers": {
    "memnex": {
      "url": "https://memory.your-company.example/mcp",
      "headers": {
        "Authorization": "Bearer mx_live_kXXXX_<secret>",
        "X-Memnex-Channel": "voice"
      }
    }
  }
}
```

The URL is wherever you deploy Memnex (Railway, Fly.io, AWS, your own VM). See [operator-guide.md](operator-guide.md) for deployment details.

## Tools

### `memory_write`

Store one or more facts about the user. Pydantic-validated; bypasses the rule-based extractor when structured `facts` are provided.

**Arguments:**
- `user_id` (string, required) — opaque tenant-chosen identifier
- `facts` (array of fact objects) — preferred; see fact shape below
- `raw_text` (string) — legacy unstructured input; runs the rule-based extractor
- `session_id` (string, optional) — opaque session label
- `trust_level` (enum, default `user_content`) — `user_content` / `agent_action` / `verified_external` / `system`
- `source` (string, optional) — free-text source label

**Fact object:**
- `fact` (string, ≤4096 chars, required)
- `type` (enum, required) — `intent` / `preference` / `issue` / `resolution` / `profile`
- `entities` (array of strings, ≤50, default `[]`) — formatted `"type:value"` (e.g. `"order:XYZ"`)
- `confidence` (number, 0.0–1.0, default 0.9)

**Example:**
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
      },
      {
        "fact": "Order XYZ never arrived",
        "type": "issue",
        "entities": ["order:XYZ"],
        "confidence": 0.9
      }
    ]
  }
}
```

**Returns:** `{"written": <int>, "memory_ids": [<string>, ...]}`

### `memory_read`

Fetch formatted memory context for one user, sized to a token budget. Call this once at the start of every turn.

**Arguments:**
- `user_id` (string, required)
- `token_budget` (integer, default 2000, max 32000)
- `target_format` (enum, optional) — `voice` / `whatsapp` / `web` / `sms` / `app`

**Returns:** `{"context": "<formatted text>"}`

### `memory_search`

Semantic search over a single user's memories.

**Arguments:**
- `user_id` (string, required)
- `query` (string, required, ≤2048 chars)
- `max_results` (integer, default 5, max 50)

**Returns:** `{"results": [{"memory_id", "fact", "type", "salience"}, ...]}`

### `memory_forget`

GDPR purge. Wipes the user's data from Redis, Postgres, Qdrant, and any pending events.

**Arguments:**
- `user_id` (string, required)
- `reason` (string, default `gdpr_request`, ≤256 chars)

**Returns:** `{"deleted_memories": <int>, "receipt": <signed receipt>}`

### `memory_trace`

Given a draft agent reply, return the source memories that could have produced it. Empty hits = suspected hallucination.

**Arguments:**
- `user_id` (string, required)
- `agent_output` (string, required, ≤50000 chars)

**Returns:** `{"hits": [{"memory_id", "fact", "score"}, ...]}`

## Resources

| URI | MIME | Returns |
|---|---|---|
| `memnex://schema/fact-types` | `text/markdown` | The 5 fact types with examples + the `entities` "type:value" convention. Read once at agent startup. |
| `memnex://users/{user_id}/memories` | `application/json` | All active memories for one user (tenant-scoped automatically). |
| `memnex://tenants/me/stats` | `application/json` | Per-tenant counts (total memories, by-type breakdown, oldest/newest timestamps). |

Resources are tenant-scoped by construction — the API key in the client config determines which tenant's data is reachable. Cross-tenant URIs are impossible.

## Prompts

| Name | Arguments | What it teaches |
|---|---|---|
| `memory-writer` | `agent_role` (optional) | When to call `memory_write` (per sub-intent), the 5 fact types, the entities convention, why structured `facts` is preferred over `raw_text`. |
| `memory-reader` | `target_format` (optional, default `web`) | How to call `memory_read` once per turn, where to fold the returned context, what NOT to do with it. |
| `hallucination-check` | `agent_output` (required) | Wraps `memory_trace`: before sending a draft, trace it; if hits is empty and the draft asserts user-specific facts, soften or ask. |

Pull these once at agent startup (or once per session) and inject them into your system prompt. They encode the best-practice usage guidance so every adopter doesn't reinvent it.

## Errors

All tools return JSON with an `error` field on failure:

| `error` | Meaning |
|---|---|
| `bad_request` | Input failed validation. `detail` field has the specific reason. |
| `forbidden` | Permission denied (typically a trust-policy violation). |
| `internal` | Unexpected server error. Includes `detail` for debugging; nothing leaks across tenants. |

Resources return `{"error": "not_found", "detail": "..."}` for unknown URIs.

## Tenant scoping

Every tool call, every resource read, and every prompt invocation is scoped by the tenant derived from the API key. The agent's LLM never sees, supplies, or has any knowledge of `tenant_id` — it works exclusively with `user_id`, which is the tenant's chosen opaque identifier for the end user.
