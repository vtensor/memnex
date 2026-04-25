"""Storage backends for Memnex.

Three tiers:
- HotStore (Redis / in-memory): working memory, identity cache. TTL'd.
- WarmStore (Postgres / in-memory): durable facts + identity graph. Tenant-isolated.
- SemanticStore (Qdrant / in-memory): vector index for similarity search.

Core code talks to protocols, not concrete backends — pick a backend via
``memnex.storage.open_stores(config)``.
"""
from memnex.storage.base import HotStore, SemanticStore, WarmStore
from memnex.storage.factory import open_stores

__all__ = ["HotStore", "WarmStore", "SemanticStore", "open_stores"]
