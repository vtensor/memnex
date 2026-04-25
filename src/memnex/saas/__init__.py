"""SaaS layer — register, login, API keys.

- :mod:`memnex.saas.accounts` — tenant accounts + passwords + JWT dashboard sessions
- :mod:`memnex.saas.keys` — API keys the tenant uses from MCP config
- :mod:`memnex.saas.routes` — FastAPI routers for the dashboard API
"""
from memnex.saas.keys import ApiKey, generate_api_key, verify_api_key

__all__ = ["ApiKey", "generate_api_key", "verify_api_key"]
