-- Query-path indexes. Create after initial bulk loads for performance.

CREATE INDEX IF NOT EXISTS idx_memories_customer
    ON memories(tenant_id, customer_id, is_active)
    WHERE is_active = TRUE;

CREATE INDEX IF NOT EXISTS idx_memories_salience
    ON memories(customer_id, salience DESC, created_at DESC)
    WHERE is_active = TRUE;

CREATE INDEX IF NOT EXISTS idx_memories_type
    ON memories(customer_id, fact_type)
    WHERE is_active = TRUE;

CREATE INDEX IF NOT EXISTS idx_memories_expiry
    ON memories(expires_at)
    WHERE expires_at IS NOT NULL AND is_active = TRUE;

CREATE INDEX IF NOT EXISTS idx_memories_session
    ON memories(session_id)
    WHERE session_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_memories_fact_fts
    ON memories USING gin (to_tsvector('english', fact));
