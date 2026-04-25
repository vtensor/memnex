# 04 — Security

## Threat model (short)

| Threat | Mitigation |
|---|---|
| Tenant A reads tenant B's data | Application tenant scoping **+** Postgres RLS safety net |
| PII leak via memory content | Mask at write time (hash / redact) |
| Unauthorized API access | `X-Memnex-API-Key` header → tenant mapping |
| GDPR forget leaves residue | Forget purges Redis + Postgres + Qdrant, returns receipt hash |
| OTPs / secrets stored forever | Per-memory TTL (`ttl_hours=1`) |
| Stolen key gives full access | Keys are tenant-scoped; can't read another tenant |
| Noisy neighbours | Per-tenant rate limit |

## Multi-tenant isolation — 5 layers

```
Layer 1: application        every query takes tenant_id
Layer 2: database (RLS)     Postgres policies, `memnex.current_tenant_id`
Layer 3: cache              Redis keys prefixed with tenant_id
Layer 4: vector store       one Qdrant collection per tenant
Layer 5: pub/sub            Redis PUBSUB payloads include tenant_id
```

RLS policies are in [migrations/002_rls_policies.sql](../src/memnex/storage/migrations/002_rls_policies.sql). They block cross-tenant reads even if application code is buggy.

## PII

- **Detected** at write: Aadhaar, PAN, credit card, email, phone, DOB, OTP.
- **Masked** before storage: `hash` (stable, matchable) or `redact` (lossy).
- **Never** logged, printed, or serialized to telemetry.
- **Extensible**: add field patterns in [privacy/pii_detector.py](../src/memnex/privacy/pii_detector.py).

## GDPR

| Operation | Guarantee |
|---|---|
| Forget | Purges hot + warm + semantic. Returns `receipt_hash` you can store as proof |
| Export | Returns all memories + identifiers in JSON |
| TTL | `expires_at` auto-enforced by the privacy worker |
| Audit | Every forget produces a hashed receipt; hook into your audit log |

## API auth

- Env var: `MEMNEX_API_KEYS="key1:tenant1,key2:tenant2"`
- Header: `X-Memnex-API-Key: <key>`
- Request's key → tenant must match the server's configured tenant; otherwise 403.
- Unset in dev = auth disabled (logs a warning). Always set in prod.

## What the library does NOT do

- No TLS termination (front it with nginx / an API gateway).
- No rate-limit coordination across instances (replace in-memory limiter with Redis for multi-process).
- No KMS-backed encryption at rest (Postgres-level TDE is your responsibility).
- No supply-chain signing (use your own build pipeline attestations).

## Secure defaults

- `pii_detection=True`
- `conflict_strategy="latest_wins"` (prevents stale facts accumulating)
- `salience_drop_threshold=0.1` (drops filler, reduces leakage surface)
- Postgres RLS on by default via `002_rls_policies.sql`
- All storage writes async + transactional where applicable

## Audit trail

Every GDPR operation produces:

```json
{
  "receipt_id": "...",
  "tenant_id": "...",
  "customer_id": "...",
  "reason": "gdpr_erasure_request",
  "timestamp": "2026-04-22T10:00:00Z",
  "deleted": {"memories": 23, "identifiers": 4, "customers": 1, "semantic_points": 23},
  "receipt_hash": "sha256:..."
}
```

Persist this in your own audit system.
