-- Memnex initial schema
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TABLE IF NOT EXISTS tenants (
    tenant_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        VARCHAR(255) NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    metadata    JSONB DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS customer_identities (
    customer_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    last_seen_at    TIMESTAMPTZ,
    last_channel    VARCHAR(50),
    metadata        JSONB DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_customer_tenant ON customer_identities(tenant_id);

CREATE TABLE IF NOT EXISTS channel_identifiers (
    identifier_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_id     UUID NOT NULL REFERENCES customer_identities(customer_id) ON DELETE CASCADE,
    tenant_id       UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
    channel         VARCHAR(50) NOT NULL,
    identifier      VARCHAR(500) NOT NULL,
    identifier_type VARCHAR(50) NOT NULL,
    confidence      FLOAT DEFAULT 1.0,
    linked_by       VARCHAR(50) DEFAULT 'system',
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (tenant_id, channel, identifier)
);
CREATE INDEX IF NOT EXISTS idx_channel_identifier
    ON channel_identifiers(tenant_id, channel, identifier);
CREATE INDEX IF NOT EXISTS idx_channel_customer
    ON channel_identifiers(tenant_id, customer_id);

CREATE TABLE IF NOT EXISTS candidate_links (
    link_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
    customer_id_a   UUID NOT NULL,
    customer_id_b   UUID NOT NULL,
    confidence      FLOAT NOT NULL,
    evidence        JSONB NOT NULL,
    status          VARCHAR(20) DEFAULT 'pending',
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_candidate_status ON candidate_links(status);
CREATE INDEX IF NOT EXISTS idx_candidate_tenant ON candidate_links(tenant_id);

CREATE TABLE IF NOT EXISTS memories (
    memory_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
    customer_id     UUID NOT NULL REFERENCES customer_identities(customer_id) ON DELETE CASCADE,
    fact            TEXT NOT NULL,
    fact_type       VARCHAR(50) NOT NULL,
    entities        TEXT[] DEFAULT '{}',
    salience        FLOAT NOT NULL DEFAULT 0.5,
    source_channel  VARCHAR(50) NOT NULL,
    source_agent_id VARCHAR(255),
    session_id      VARCHAR(255),
    superseded_by   UUID REFERENCES memories(memory_id),
    is_active       BOOLEAN DEFAULT TRUE,
    embedding_id    VARCHAR(255),
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    expires_at      TIMESTAMPTZ,
    contains_pii    BOOLEAN DEFAULT FALSE,
    pii_fields      TEXT[] DEFAULT '{}',
    consent_basis   VARCHAR(50) DEFAULT 'legitimate_interest'
);
