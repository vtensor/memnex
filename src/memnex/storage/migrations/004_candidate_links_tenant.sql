-- Upgrade migration: add tenant_id to candidate_links for pre-existing
-- deployments that ran 001_initial.sql before tenant_id was added.
-- Safe to re-run: IF NOT EXISTS guards.

ALTER TABLE candidate_links
    ADD COLUMN IF NOT EXISTS tenant_id UUID;

-- Backfill: derive tenant_id from customer_id_a.
UPDATE candidate_links cl
SET tenant_id = ci.tenant_id
FROM customer_identities ci
WHERE cl.customer_id_a = ci.customer_id
  AND cl.tenant_id IS NULL;

-- Tighten to NOT NULL now that backfill is done.
ALTER TABLE candidate_links
    ALTER COLUMN tenant_id SET NOT NULL;

-- Add FK + index.
ALTER TABLE candidate_links
    DROP CONSTRAINT IF EXISTS candidate_links_tenant_fk;
ALTER TABLE candidate_links
    ADD CONSTRAINT candidate_links_tenant_fk
    FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id) ON DELETE CASCADE;

CREATE INDEX IF NOT EXISTS idx_candidate_tenant ON candidate_links(tenant_id);

-- Row-level security safety net.
ALTER TABLE candidate_links ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_candidate_links ON candidate_links;
CREATE POLICY tenant_isolation_candidate_links ON candidate_links
    USING (tenant_id = current_setting('memnex.current_tenant_id', true)::UUID);
