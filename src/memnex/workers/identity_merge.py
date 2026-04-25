"""Identity merge worker.

Consumes confirmed candidate_links and merges the memory graphs of the two
customers into one. The merge is non-destructive: the "losing" customer's
memories are re-parented; identifiers get pointed to the surviving customer.
"""
from __future__ import annotations

from memnex.client import Memnex


class IdentityMergeWorker:
    def __init__(self, mx: Memnex) -> None:
        self._mx = mx

    async def merge(self, surviving_id: str, other_id: str) -> dict:
        warm = self._mx._stores.warm
        tenant = self._mx.config.tenant_id

        # Re-parent memories.
        memories = await warm.list_memories(tenant, other_id, limit=10_000, active_only=False)
        for m in memories:
            updated = m.model_copy(update={"customer_id": surviving_id})
            await warm.insert_memory(updated)

        # Re-parent identifiers.
        idents = await warm.list_identifiers(tenant, other_id)
        for ident in idents:
            new_ident = ident.model_copy(update={"customer_id": surviving_id})
            await warm.add_identifier(new_ident)

        # Delete the losing customer.
        counts = await warm.delete_customer(tenant, other_id)
        await self._mx._stores.hot.invalidate(tenant, other_id)
        await self._mx._stores.hot.invalidate(tenant, surviving_id)

        return {
            "surviving_customer": surviving_id,
            "merged_from": other_id,
            "memories_moved": len(memories),
            "identifiers_moved": len(idents),
            "deleted": counts,
        }
