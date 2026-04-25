# Security Policy

## Reporting a vulnerability

Please report suspected security issues **privately** to **vikramdev.iitd@gmail.com**.

Do not file a public GitHub issue for security reports. We will acknowledge receipt within 7 days and aim to provide an initial assessment within 14 days. Once a fix is ready, we will coordinate disclosure timing with you.

## What to include

- A clear description of the issue and its potential impact.
- Steps to reproduce, ideally with a minimal example.
- The Memnex version (`pip show memnex`) and the storage backends in use.
- Whether you have already shared the issue with anyone else.

## Supported versions

| Version | Supported           |
|---------|---------------------|
| 0.1.x   | ✅ active support   |
| < 0.1   | ❌ not supported    |

## Scope

In scope:

- The Memnex Python package (`src/memnex/`)
- The MCP server (`memnex serve mcp`)
- The REST API (`memnex serve rest`)
- The SaaS routes (`memnex.saas.routes`)
- Storage backends shipped in this repo

Out of scope:

- Issues caused by misconfiguration on the operator's side (e.g. running with `MEMNEX_DEV_KEY=1` in production).
- Issues in third-party dependencies — please report to the upstream project.
- Theoretical issues without a working proof-of-concept against current main.

## Safe-harbour

We will not pursue legal action against researchers who:

- Make a good-faith effort to avoid privacy violations or service disruption while testing.
- Report the issue privately and give us a reasonable window to fix it before disclosure.
- Do not exploit the issue beyond what is necessary to demonstrate it.

Thank you for helping keep Memnex and its users safe.
