"""Concurrency guarantees for Memnex.

Three mechanisms:

1. **Append-only ledger** (:class:`WriteLedger`) — every write lands in a
   durable append-only log before the memory row is visible. If a hot-path
   write to Postgres fails, the ledger is the source of truth.
2. **Per-user optimistic version** (:class:`VersionClock`) — each
   ``(tenant_id, user_id)`` has a monotonic version. Every write bumps it.
   Readers can request ``if_version=N`` for read-after-write guarantees.
3. **Cache invalidation bus** (:class:`InvalidationBus`) — every write
   publishes to a channel that all Memnex instances subscribe to. Local
   working-memory caches drop stale entries within the publish RTT.
"""
from memnex.concurrency.bus import InvalidationBus, InProcessBus
from memnex.concurrency.ledger import WriteLedger, LedgerEntry
from memnex.concurrency.versions import VersionClock

__all__ = [
    "WriteLedger",
    "LedgerEntry",
    "VersionClock",
    "InvalidationBus",
    "InProcessBus",
]
