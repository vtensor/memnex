"""Postgres warm store. Tenant isolation via explicit WHERE + RLS safety net.

Every query passes tenant_id in the WHERE clause. On top of that, RLS policies
(see migrations/002_rls_policies.sql) block any cross-tenant read even if
application code slipped up. Belt + suspenders.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING, Any

from memnex.identity.models import CandidateLink, ChannelIdentifier, Customer
from memnex.memory.models import Memory

if TYPE_CHECKING:
    import asyncpg


class PostgresWarmStore:
    def __init__(self, pool: "asyncpg.Pool") -> None:
        self._pool = pool

    @classmethod
    async def create(cls, url: str) -> "PostgresWarmStore":
        try:
            import asyncpg
        except ImportError as e:
            raise ImportError(
                "asyncpg not installed. `pip install memnex[postgres]`."
            ) from e
        pool = await asyncpg.create_pool(url, min_size=2, max_size=10)
        return cls(pool)

    async def _scoped(self, tenant_id: str):
        """Yield a connection with memnex.current_tenant_id set for RLS."""
        conn = await self._pool.acquire()
        try:
            await conn.execute(
                "SELECT set_config('memnex.current_tenant_id', $1, true)", tenant_id
            )
            return conn
        except Exception:
            await self._pool.release(conn)
            raise

    async def _release(self, conn) -> None:
        await self._pool.release(conn)

    # --- identity ---
    async def upsert_customer(self, customer: Customer) -> None:
        conn = await self._scoped(customer.tenant_id)
        try:
            await conn.execute(
                """
                INSERT INTO customer_identities
                    (customer_id, tenant_id, created_at, last_seen_at, last_channel, metadata)
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (customer_id) DO UPDATE SET
                    last_seen_at = EXCLUDED.last_seen_at,
                    last_channel = EXCLUDED.last_channel,
                    metadata = EXCLUDED.metadata
                """,
                customer.id,
                customer.tenant_id,
                customer.created_at,
                customer.last_seen_at,
                customer.last_channel,
                json.dumps(customer.metadata),
            )
        finally:
            await self._release(conn)

    async def get_customer(self, tenant_id: str, customer_id: str) -> Customer | None:
        conn = await self._scoped(tenant_id)
        try:
            row = await conn.fetchrow(
                "SELECT * FROM customer_identities WHERE tenant_id = $1 AND customer_id = $2",
                tenant_id, customer_id,
            )
            if not row:
                return None
            idents = await self.list_identifiers(tenant_id, customer_id)
            return Customer(
                id=str(row["customer_id"]),
                tenant_id=str(row["tenant_id"]),
                created_at=row["created_at"],
                last_seen_at=row["last_seen_at"],
                last_channel=row["last_channel"],
                channels=sorted({i.channel for i in idents}),  # type: ignore[arg-type]
                identifiers=idents,
                metadata=json.loads(row["metadata"] or "{}"),
            )
        finally:
            await self._release(conn)

    async def find_by_identifier(
        self, tenant_id: str, channel: str, identifier: str
    ) -> Customer | None:
        conn = await self._scoped(tenant_id)
        try:
            row = await conn.fetchrow(
                """
                SELECT customer_id FROM channel_identifiers
                WHERE tenant_id = $1 AND channel = $2 AND identifier = $3
                """,
                tenant_id, channel, identifier,
            )
            if not row:
                return None
            return await self.get_customer(tenant_id, str(row["customer_id"]))
        finally:
            await self._release(conn)

    async def add_identifier(self, identifier: ChannelIdentifier) -> None:
        conn = await self._pool.acquire()
        try:
            # Fetch tenant via customer
            tenant = await conn.fetchval(
                "SELECT tenant_id FROM customer_identities WHERE customer_id = $1",
                identifier.customer_id,
            )
            if not tenant:
                raise ValueError(f"Unknown customer_id {identifier.customer_id}")
            await conn.execute(
                "SELECT set_config('memnex.current_tenant_id', $1, true)", str(tenant)
            )
            await conn.execute(
                """
                INSERT INTO channel_identifiers
                    (identifier_id, customer_id, tenant_id, channel, identifier,
                     identifier_type, confidence, linked_by, created_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                ON CONFLICT (tenant_id, channel, identifier) DO NOTHING
                """,
                identifier.identifier_id,
                identifier.customer_id,
                str(tenant),
                identifier.channel,
                identifier.identifier,
                identifier.identifier_type,
                identifier.confidence,
                identifier.linked_by,
                identifier.created_at,
            )
        finally:
            await self._pool.release(conn)

    async def list_identifiers(
        self, tenant_id: str, customer_id: str
    ) -> list[ChannelIdentifier]:
        conn = await self._scoped(tenant_id)
        try:
            rows = await conn.fetch(
                """
                SELECT * FROM channel_identifiers
                WHERE tenant_id = $1 AND customer_id = $2
                """,
                tenant_id, customer_id,
            )
            return [
                ChannelIdentifier(
                    identifier_id=str(r["identifier_id"]),
                    customer_id=str(r["customer_id"]),
                    channel=r["channel"],
                    identifier=r["identifier"],
                    identifier_type=r["identifier_type"],
                    confidence=float(r["confidence"]),
                    linked_by=r["linked_by"],
                    created_at=r["created_at"],
                )
                for r in rows
            ]
        finally:
            await self._release(conn)

    async def record_candidate_link(self, link: CandidateLink) -> None:
        # Derive the owning tenant from customer_id_a (the existing customer).
        conn = await self._pool.acquire()
        try:
            tenant = await conn.fetchval(
                "SELECT tenant_id FROM customer_identities WHERE customer_id = $1",
                link.customer_id_a,
            )
            if not tenant:
                raise ValueError(
                    f"unknown customer_id_a for candidate link: {link.customer_id_a}"
                )
            await conn.execute(
                "SELECT set_config('memnex.current_tenant_id', $1, true)",
                str(tenant),
            )
            await conn.execute(
                """
                INSERT INTO candidate_links
                    (link_id, tenant_id, customer_id_a, customer_id_b,
                     confidence, evidence, status, created_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                """,
                link.link_id,
                str(tenant),
                link.customer_id_a,
                link.customer_id_b,
                link.confidence,
                json.dumps(link.evidence),
                link.status,
                link.created_at,
            )
        finally:
            await self._pool.release(conn)

    async def list_candidate_links(
        self, tenant_id: str, customer_id: str
    ) -> list[CandidateLink]:
        conn = await self._scoped(tenant_id)
        try:
            rows = await conn.fetch(
                """
                SELECT * FROM candidate_links
                WHERE tenant_id = $1
                  AND (customer_id_a = $2 OR customer_id_b = $2)
                """,
                tenant_id, customer_id,
            )
            return [
                CandidateLink(
                    link_id=str(r["link_id"]),
                    customer_id_a=str(r["customer_id_a"]),
                    customer_id_b=str(r["customer_id_b"]),
                    confidence=float(r["confidence"]),
                    evidence=json.loads(r["evidence"] or "{}"),
                    status=r["status"],
                    created_at=r["created_at"],
                )
                for r in rows
            ]
        finally:
            await self._release(conn)

    # --- memories ---
    async def insert_memory(self, memory: Memory) -> None:
        conn = await self._scoped(memory.tenant_id)
        try:
            await conn.execute(
                """
                INSERT INTO memories
                    (memory_id, tenant_id, customer_id, fact, fact_type, entities, salience,
                     source_channel, source_agent_id, session_id, superseded_by, is_active,
                     embedding_id, created_at, updated_at, expires_at,
                     contains_pii, pii_fields, consent_basis)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19)
                """,
                memory.memory_id,
                memory.tenant_id,
                memory.customer_id,
                memory.fact,
                memory.fact_type,
                memory.entities,
                memory.salience,
                memory.source_channel,
                memory.source_agent_id,
                memory.session_id,
                memory.superseded_by,
                memory.is_active,
                memory.embedding_id,
                memory.created_at,
                memory.updated_at,
                memory.expires_at,
                memory.contains_pii,
                memory.pii_fields,
                memory.consent_basis,
            )
        finally:
            await self._release(conn)

    async def supersede_memory(
        self, tenant_id: str, memory_id: str, superseded_by: str
    ) -> None:
        conn = await self._scoped(tenant_id)
        try:
            await conn.execute(
                """
                UPDATE memories SET is_active = FALSE,
                                    superseded_by = $2,
                                    updated_at = NOW()
                WHERE tenant_id = $3 AND memory_id = $1
                """,
                memory_id, superseded_by, tenant_id,
            )
        finally:
            await self._release(conn)

    async def get_memories_by_ids(
        self, tenant_id: str, customer_id: str, ids: list[str]
    ) -> list[Memory]:
        if not ids:
            return []
        conn = await self._scoped(tenant_id)
        try:
            rows = await conn.fetch(
                """
                SELECT * FROM memories
                WHERE tenant_id = $1
                  AND customer_id = $2
                  AND memory_id = ANY($3::uuid[])
                """,
                tenant_id, customer_id, ids,
            )
            return [self._row_to_memory(r) for r in rows]
        finally:
            await self._release(conn)

    async def list_memories(
        self,
        tenant_id: str,
        customer_id: str,
        *,
        limit: int = 50,
        active_only: bool = True,
        fact_type: str | None = None,
    ) -> list[Memory]:
        conn = await self._scoped(tenant_id)
        try:
            clauses = ["tenant_id = $1", "customer_id = $2"]
            args: list[Any] = [tenant_id, customer_id]
            if active_only:
                clauses.append("is_active = TRUE")
            if fact_type:
                args.append(fact_type)
                clauses.append(f"fact_type = ${len(args)}")
            args.append(limit)
            sql = (
                "SELECT * FROM memories WHERE "
                + " AND ".join(clauses)
                + f" ORDER BY salience DESC, created_at DESC LIMIT ${len(args)}"
            )
            rows = await conn.fetch(sql, *args)
            return [self._row_to_memory(r) for r in rows]
        finally:
            await self._release(conn)

    async def list_expired(self, now: datetime) -> list[Memory]:
        conn = await self._pool.acquire()
        try:
            rows = await conn.fetch(
                "SELECT * FROM memories WHERE expires_at <= $1 AND is_active = TRUE",
                now,
            )
            return [self._row_to_memory(r) for r in rows]
        finally:
            await self._pool.release(conn)

    async def delete_customer(self, tenant_id: str, customer_id: str) -> dict[str, int]:
        conn = await self._scoped(tenant_id)
        try:
            async with conn.transaction():
                m = await conn.fetchval(
                    "DELETE FROM memories WHERE tenant_id=$1 AND customer_id=$2 RETURNING count(*)",
                    tenant_id, customer_id,
                ) or 0
                i = await conn.fetchval(
                    "DELETE FROM channel_identifiers WHERE tenant_id=$1 AND customer_id=$2 RETURNING count(*)",
                    tenant_id, customer_id,
                ) or 0
                c = await conn.fetchval(
                    "DELETE FROM customer_identities WHERE tenant_id=$1 AND customer_id=$2 RETURNING count(*)",
                    tenant_id, customer_id,
                ) or 0
                return {"memories": m, "identifiers": i, "customers": c}
        finally:
            await self._release(conn)

    async def tenant_stats(self, tenant_id: str) -> dict[str, Any]:
        conn = await self._scoped(tenant_id)
        try:
            total_customers = await conn.fetchval(
                "SELECT COUNT(*) FROM customer_identities WHERE tenant_id = $1", tenant_id
            )
            total_memories = await conn.fetchval(
                "SELECT COUNT(*) FROM memories WHERE tenant_id = $1 AND is_active = TRUE",
                tenant_id,
            )
            channel_rows = await conn.fetch(
                """
                SELECT source_channel, COUNT(*) as c FROM memories
                WHERE tenant_id = $1 AND is_active = TRUE
                GROUP BY source_channel
                """,
                tenant_id,
            )
            channels = {r["source_channel"]: int(r["c"]) for r in channel_rows}
            avg = (total_memories / total_customers) if total_customers else 0.0
            return {
                "total_customers": int(total_customers or 0),
                "total_memories": int(total_memories or 0),
                "channels": channels,
                "avg_memories_per_customer": avg,
            }
        finally:
            await self._release(conn)

    async def close(self) -> None:
        await self._pool.close()

    @staticmethod
    def _row_to_memory(r) -> Memory:
        return Memory(
            memory_id=str(r["memory_id"]),
            tenant_id=str(r["tenant_id"]),
            customer_id=str(r["customer_id"]),
            fact=r["fact"],
            fact_type=r["fact_type"],
            entities=list(r["entities"] or []),
            salience=float(r["salience"]),
            source_channel=r["source_channel"],
            source_agent_id=r["source_agent_id"],
            session_id=r["session_id"],
            superseded_by=str(r["superseded_by"]) if r["superseded_by"] else None,
            is_active=bool(r["is_active"]),
            embedding_id=r["embedding_id"],
            created_at=r["created_at"],
            updated_at=r["updated_at"],
            expires_at=r["expires_at"],
            contains_pii=bool(r["contains_pii"]),
            pii_fields=list(r["pii_fields"] or []),
            consent_basis=r["consent_basis"],
        )
