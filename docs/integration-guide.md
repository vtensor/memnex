# Integration guide (for tenants)

This is the guide for **someone integrating an AI agent with Memnex**. If you are running Memnex itself, see [operator-guide.md](operator-guide.md) instead.

There are exactly two things you need to do.

1. Get an API key.
2. Point your agent's MCP client at Memnex.

That's it. You will never set a Postgres URL, a Google API key, or a tenant id. Those are the operator's concern.

---

## Step 1 — Get an API key

Memnex is self-hosted today, so the API key comes from whoever runs your Memnex instance. If that's you and your team, the operator side issues one via:

```bash
# operator side
memnex saas create-key --label "voice-agent"
# prints: mx_live_kXXXX_<secret>
```

For local development, shortcut all of this with `MEMNEX_DEV_KEY=1` when starting the server — it auto-creates a throwaway tenant and prints a single-use API key on boot. See [operator-guide.md](operator-guide.md) for the full setup.

The key looks like `mx_live_kXXXXXXXX_<44 base64 chars>`. Treat it as a secret — anyone with it can read and write that tenant's memory.

---

## Step 2 — Point your agent at Memnex

Pick the row that matches your runtime.

### Claude Desktop / Cursor / Cline / any stdio-MCP client

The most portable option: point the client at the `memnex` CLI as a subprocess. The MCP server runs as a child process of your client.

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

If your runtime supports remote MCP over HTTP, point it at your operator's `streamable-http` endpoint:

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

The exact URL depends on where your operator deployed Memnex (`memnex serve mcp --transport streamable-http`). Ask them.

Set `MEMNEX_CHANNEL` to the channel this particular agent represents:

| Value | Use it for |
|---|---|
| `voice` | Voice / phone agents |
| `whatsapp` | WhatsApp / messaging agents |
| `web` | Web chat widgets |
| `sms` | SMS bots |
| `app` | In-app assistants (default) |

It only affects how `memory_read` formats its output. Voice gets terse bullets; web gets richer markdown.

### LangGraph / LangChain agents

Use any MCP adapter (e.g. `langchain-mcp`). Point it at the same URL or stdio command above.

### REST (no MCP support)

```bash
curl -X POST https://memory.your-company.example/api/v1/memory/write \
  -H "X-Memnex-API-Key: mx_live_kXXXX_<secret>" \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "u_123",
    "channel": "voice",
    "facts": [
      {"fact": "Wants to cancel order XYZ",
       "type": "intent",
       "entities": ["order:XYZ"]}
    ]
  }'
```

The full REST surface is in [api-reference.md](api-reference.md).

---

## Step 3 — Teach your agent how to use Memnex

Memnex ships three **prompts** that explain when and how to use the tools. Your runtime can pull them at startup and inject them into your agent's system prompt — no need to write your own guidance from scratch.

```python
# pseudocode — exact API depends on your MCP client
prompts = mcp_client.list_prompts()
writer = mcp_client.get_prompt("memory-writer", arguments={"agent_role": "support agent"})
reader = mcp_client.get_prompt("memory-reader", arguments={"target_format": "voice"})
system_prompt = "\n\n".join([
    your_normal_system_prompt,
    writer.messages[0].content,
    reader.messages[0].content,
])
```

The three prompts are:

| Prompt | When to pull |
|---|---|
| `memory-writer` | At agent startup. Teaches when to call `memory_write` (per sub-intent, not at end of conversation). |
| `memory-reader` | At agent startup. Teaches how to call `memory_read` once per turn and where to fold the context. |
| `hallucination-check` | Before sending a draft reply. Wraps `memory_trace` to verify claims. |

Or, if you'd rather embed the guidance directly, read [`memnex://schema/fact-types`](mcp.md) — it's a markdown resource your runtime can `read_resource()` once at startup.

---

## Step 4 — Test the round-trip

```python
# Have the agent write something on one channel...
agent_voice.handle_user_message("My order #4521 arrived broken")
# (the agent calls memory_write internally)

# ...then read on a different channel
agent_whatsapp.start_conversation(user_id="u_123")
# memory_read returns: "Previous (voice, 2m ago): Order #4521 arrived damaged."
```

If you see the cross-channel context, you're done. If not, see [Troubleshooting](#troubleshooting).

---

## What goes in `user_id`?

Whatever stable identifier you have for your end user. Memnex treats it as opaque — the only requirement is that **the same person uses the same `user_id` across every channel and every agent**. Common choices:

- A row id from your users table (`"u_123"`, `"7af3b1..."`)
- The phone number, normalized (`"+919241063955"`)
- An email (`"vikram@example.com"`)
- An external auth subject (`"google-oauth2|abc"`)

Don't use channel-specific identifiers — `"wa:..."` and `"+91..."` for the same person would create two separate memory streams.

If your data only has channel-specific ids, use the [identity resolution APIs](api-reference.md#rest) (`/identity/link`) to merge them server-side.

---

## What does the agent actually do?

The 5 tools, in the order you'll typically use them:

1. **`memory_read`** — first call of the turn. Returns formatted context.
2. **`memory_search`** — when the user mentions something specific you want to look up ("about my last refund").
3. **`memory_write`** — the moment a fact crystallizes during the turn (intent stated, preference revealed, issue raised, resolution closed). Write per sub-intent, not in a batch at the end.
4. **`memory_trace`** — before sending a draft reply, verify it against memory.
5. **`memory_forget`** — when the user requests deletion under GDPR / CCPA / DPDP.

Full schemas in [mcp.md](mcp.md).

---

## Troubleshooting

### `unknown API key`
Your `MEMNEX_SECRET_KEY` is wrong, expired, or for a different environment (staging vs production). Check the dashboard.

### `MEMNEX_SECRET_KEY is required in MCP config`
The env var didn't reach the server process. In Claude Desktop, restart the app after editing the config — env changes don't hot-reload. In stdio mode, make sure `env` is inside the right block (per-server, not at the top level).

### Cross-channel handoff isn't working — second agent doesn't see what the first wrote
Check that both agents use the **same `user_id`**. Channel-specific identifiers won't merge automatically. If they must (e.g. you only have a phone number on voice and only a session id on web), call `/identity/link` once to merge.

### Memory is "empty" but I just wrote
Two common causes:
- The fact got dropped because its salience score was below `0.1`. Filler text ("hello", "thanks") falls in this range. Add more specific content, or include `entities`.
- You wrote on tenant A's key but are reading on tenant B's key. Tenant scoping is enforced at the API key layer.

### How do I delete a user's data for GDPR?
Call `memory_forget(user_id=...)`. It returns a signed receipt confirming the purge across all stores. Keep the receipt; that's your audit trail.

### Where do I see what the agent has stored?
Read the resource `memnex://users/{user_id}/memories` — JSON dump of all active memories for that user, tenant-scoped. Useful for a "what we know about you" UI.

---

## Next reading

- [mcp.md](mcp.md) — full MCP API reference (all tools, resources, prompts with schemas)
- [api-reference.md](api-reference.md) — REST API
- [security.md](security.md) — what Memnex does and doesn't protect against
- [comparison.md](comparison.md) — how Memnex compares to Mem0, Zep, Letta, OpenAI memory
