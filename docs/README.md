# Memnex documentation

Pick the doc that matches what you're trying to do.

## By role

| If you are... | Start with |
|---|---|
| **Integrating an AI agent with Memnex** (most common) | [integration-guide.md](integration-guide.md) |
| **Running Memnex itself** (self-hosting or as service operator) | [operator-guide.md](operator-guide.md) |
| **Contributing to Memnex** (extending, fixing, releasing) | [../CONTRIBUTING.md](../CONTRIBUTING.md) + [publishing.md](publishing.md) |
| **Just exploring** | The [project README](../README.md), then [architecture.md](architecture.md) |

## Reference docs

| Doc | What's in it |
|---|---|
| [architecture.md](architecture.md) | System design, data flow, the four invariants. Read this to understand *how* Memnex works internally. |
| [mcp.md](mcp.md) | Full MCP API reference — 5 tools, 3 resources, 3 prompts, schemas, error shapes. |
| [api-reference.md](api-reference.md) | REST API, Python embedded API, CLI commands. Audience-tagged so each section is clearly tenant- or operator-facing. |
| [security.md](security.md) | Multi-tenant isolation, audit ledger, regulated PII handling, injection floor. |
| [features.md](features.md) | What's built today and what's intentionally out of scope. |
| [deployment.md](deployment.md) | Docker compose, scaling, env vars. |
| [eval.md](eval.md) | The six benchmark suites and how to run them. |
| [comparison.md](comparison.md) | How Memnex compares to Mem0, Zep, Letta, OpenAI memory. |
| [roadmap.md](roadmap.md) | What's next and why, in three priority tiers. |
| [publishing.md](publishing.md) | How releases get to PyPI. Maintainer-facing. |

## Suggested reading paths

**First-time tenant integrating an agent:**
[integration-guide.md](integration-guide.md) → [mcp.md](mcp.md) → done.

**Operator setting up self-hosted Memnex:**
[operator-guide.md](operator-guide.md) → [deployment.md](deployment.md) → [security.md](security.md).

**Engineer evaluating Memnex against alternatives:**
[architecture.md](architecture.md) → [comparison.md](comparison.md) → [features.md](features.md) → [roadmap.md](roadmap.md).

**Maintainer cutting a release:**
[../CONTRIBUTING.md](../CONTRIBUTING.md) → [publishing.md](publishing.md) → [../CHANGELOG.md](../CHANGELOG.md).
