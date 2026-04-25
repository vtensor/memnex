"""Memory TTL enforcement.

A background worker calls :func:`enforce` on a schedule; the core library
calls it inline only from the CLI ``memnex db vacuum`` command.
"""
from __future__ import annotations

from memnex._time import utcnow

from datetime import datetime

from memnex.storage.base import WarmStore


async def enforce(warm: WarmStore, *, now: datetime | None = None) -> int:
    """Mark expired memories as inactive. Returns the number affected."""
    expired = await warm.list_expired(now or utcnow())
    for m in expired:
        await warm.supersede_memory(
            m.tenant_id, m.memory_id, superseded_by=m.memory_id,
        )
    return len(expired)
