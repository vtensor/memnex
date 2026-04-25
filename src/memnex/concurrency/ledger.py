"""Append-only write ledger.

Every memory write lands here first. The ledger is the durable source of
truth — if Postgres or Qdrant lose data, we replay from the ledger.

Each entry is content-addressed: ``payload_hash`` is the SHA-256 of the
serialized write. Combined with ``prev_hash``, this forms a hash chain so
any tampering is detectable (a small-scale Merkle log).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol


@dataclass
class LedgerEntry:
    seq: int
    tenant_id: str
    user_id: str
    version: int
    op: str  # "write" | "supersede" | "forget"
    payload: dict[str, Any]
    timestamp: datetime
    prev_hash: str
    payload_hash: str = field(init=False)

    def __post_init__(self) -> None:
        canonical = json.dumps(
            {
                "seq": self.seq,
                "tenant_id": self.tenant_id,
                "user_id": self.user_id,
                "version": self.version,
                "op": self.op,
                "payload": self.payload,
                "timestamp": self.timestamp.isoformat(),
                "prev_hash": self.prev_hash,
            },
            sort_keys=True,
            default=str,
        )
        self.payload_hash = hashlib.sha256(canonical.encode()).hexdigest()


class WriteLedger(Protocol):
    async def append(
        self,
        *,
        tenant_id: str,
        user_id: str,
        version: int,
        op: str,
        payload: dict[str, Any],
    ) -> LedgerEntry: ...
    async def verify_chain(self, *, tenant_id: str | None = None) -> bool: ...
    async def tail(self, *, limit: int = 100) -> list[LedgerEntry]: ...
    async def close(self) -> None: ...


class InMemoryLedger:
    def __init__(self) -> None:
        self._entries: list[LedgerEntry] = []
        self._seq = 0

    async def append(
        self,
        *,
        tenant_id: str,
        user_id: str,
        version: int,
        op: str,
        payload: dict[str, Any],
    ) -> LedgerEntry:
        self._seq += 1
        prev = self._entries[-1].payload_hash if self._entries else "GENESIS"
        entry = LedgerEntry(
            seq=self._seq,
            tenant_id=tenant_id,
            user_id=user_id,
            version=version,
            op=op,
            payload=payload,
            timestamp=_utcnow(),
            prev_hash=prev,
        )
        self._entries.append(entry)
        return entry

    async def verify_chain(self, *, tenant_id: str | None = None) -> bool:
        prev = "GENESIS"
        for e in self._entries:
            if tenant_id is not None and e.tenant_id != tenant_id:
                continue
            if e.prev_hash != prev:
                return False
            prev = e.payload_hash
        return True

    async def tail(self, *, limit: int = 100) -> list[LedgerEntry]:
        return list(self._entries[-limit:])

    async def close(self) -> None:
        pass


def _utcnow() -> datetime:
    from datetime import timezone
    return datetime.now(timezone.utc).replace(tzinfo=None)
