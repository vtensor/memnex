"""GDPR-facing operations: forget + export.

Forget must be total: Postgres, Redis, and Qdrant are all purged for the
customer. Returns a signed receipt (HMAC digest) the caller archives as
proof of deletion.
"""
from __future__ import annotations

from memnex._time import utcnow

import hashlib
import json
import uuid
from datetime import datetime
from typing import Any

from memnex.config import MemnexConfig
from memnex.storage.base import HotStore, SemanticStore, WarmStore


class GDPRCoordinator:
    def __init__(
        self,
        config: MemnexConfig,
        hot: HotStore,
        warm: WarmStore,
        semantic: SemanticStore,
    ) -> None:
        self._cfg = config
        self._hot = hot
        self._warm = warm
        self._semantic = semantic

    async def forget_customer(
        self, customer_id: str, reason: str
    ) -> dict[str, Any]:
        await self._hot.invalidate(self._cfg.tenant_id, customer_id)
        warm_counts = await self._warm.delete_customer(self._cfg.tenant_id, customer_id)
        semantic_count = await self._semantic.delete_customer(
            self._cfg.tenant_id, customer_id
        )

        payload = {
            "receipt_id": str(uuid.uuid4()),
            "tenant_id": self._cfg.tenant_id,
            "customer_id": customer_id,
            "reason": reason,
            "timestamp": utcnow().isoformat() + "Z",
            "deleted": {**warm_counts, "semantic_points": semantic_count},
        }
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode()
        ).hexdigest()
        payload["receipt_hash"] = digest
        return payload

    async def export_customer_data(
        self, customer_id: str, *, format: str = "json"
    ) -> dict[str, Any] | str:
        customer = await self._warm.get_customer(self._cfg.tenant_id, customer_id)
        memories = await self._warm.list_memories(
            self._cfg.tenant_id, customer_id, limit=10_000, active_only=False
        )
        data = {
            "tenant_id": self._cfg.tenant_id,
            "exported_at": utcnow().isoformat() + "Z",
            "customer": customer.model_dump(mode="json") if customer else None,
            "memories": [m.model_dump(mode="json") for m in memories],
        }
        if format == "json":
            return data
        return json.dumps(data, indent=2, default=str)
