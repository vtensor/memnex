-- Row-level security. Application code must always call
--   SELECT set_config('memnex.current_tenant_id', <tenant>, true);
-- before executing tenant-scoped queries. These policies are the safety net.

ALTER TABLE customer_identities ENABLE ROW LEVEL SECURITY;
ALTER TABLE channel_identifiers ENABLE ROW LEVEL SECURITY;
ALTER TABLE memories             ENABLE ROW LEVEL SECURITY;
ALTER TABLE candidate_links      ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_isolation_customers ON customer_identities;
CREATE POLICY tenant_isolation_customers ON customer_identities
    USING (tenant_id = current_setting('memnex.current_tenant_id', true)::UUID);

DROP POLICY IF EXISTS tenant_isolation_identifiers ON channel_identifiers;
CREATE POLICY tenant_isolation_identifiers ON channel_identifiers
    USING (tenant_id = current_setting('memnex.current_tenant_id', true)::UUID);

DROP POLICY IF EXISTS tenant_isolation_memories ON memories;
CREATE POLICY tenant_isolation_memories ON memories
    USING (tenant_id = current_setting('memnex.current_tenant_id', true)::UUID);

DROP POLICY IF EXISTS tenant_isolation_candidate_links ON candidate_links;
CREATE POLICY tenant_isolation_candidate_links ON candidate_links
    USING (tenant_id = current_setting('memnex.current_tenant_id', true)::UUID);
