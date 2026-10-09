-- Deep Trekker AI v1.1 central schema (PostgreSQL / Supabase).
-- Mirrors the SQLite v1 tables; JSON stays TEXT. Safe to re-run.

CREATE TABLE IF NOT EXISTS customers (
    id BIGSERIAL PRIMARY KEY,
    customer_id TEXT NOT NULL UNIQUE,
    customer_name TEXT NOT NULL,
    department TEXT,
    contact_name TEXT,
    email TEXT,
    phone TEXT,
    address TEXT,
    end_user TEXT,
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS technical_cases (
    id BIGSERIAL PRIMARY KEY,
    case_id TEXT NOT NULL UNIQUE,
    customer_name TEXT,
    case_title TEXT,
    status TEXT,
    provider TEXT,
    model TEXT,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    schema_version INTEGER NOT NULL,
    archived_at TEXT,
    deleted_at TEXT,
    parent_case_id TEXT,
    relation_type TEXT,
    case_lifecycle_status TEXT NOT NULL DEFAULT 'ACTIVE',
    close_reason TEXT,
    closed_at TEXT,
    closed_by TEXT,
    close_memo TEXT,
    created_by TEXT,
    updated_by TEXT,
    row_version INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_technical_cases_updated ON technical_cases(updated_at DESC);

CREATE TABLE IF NOT EXISTS technical_case_response_revisions (
    id BIGSERIAL PRIMARY KEY,
    case_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    provider TEXT,
    model TEXT,
    analyzed_at TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    schema_version INTEGER NOT NULL,
    UNIQUE (case_id, revision)
);

CREATE TABLE IF NOT EXISTS quote_drafts (
    id BIGSERIAL PRIMARY KEY,
    quote_draft_id TEXT NOT NULL,
    case_id TEXT,
    version INTEGER NOT NULL,
    status TEXT,
    customer_name TEXT,
    subject TEXT,
    configuration_name TEXT,
    payload_json TEXT NOT NULL,
    ui_state_json TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    schema_version INTEGER NOT NULL,
    archived_at TEXT,
    deleted_at TEXT,
    parent_quote_id TEXT,
    source_quote_id TEXT,
    relation_type TEXT,
    created_by TEXT,
    updated_by TEXT,
    row_version INTEGER NOT NULL DEFAULT 1,
    UNIQUE (quote_draft_id, version)
);
CREATE INDEX IF NOT EXISTS idx_quote_drafts_updated ON quote_drafts(updated_at DESC);

CREATE TABLE IF NOT EXISTS approved_quote_snapshots (
    id BIGSERIAL PRIMARY KEY,
    approved_quote_snapshot_id TEXT NOT NULL UNIQUE,
    quote_draft_id TEXT NOT NULL,
    quote_version INTEGER NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    schema_version INTEGER NOT NULL,
    approved_by TEXT
);

CREATE TABLE IF NOT EXISTS activity_events (
    id BIGSERIAL PRIMARY KEY,
    event_id TEXT NOT NULL UNIQUE,
    event_type TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    entity_kind TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    entity_version INTEGER,
    customer_name TEXT,
    title TEXT,
    payload_json TEXT NOT NULL,
    schema_version INTEGER NOT NULL,
    actor_email TEXT
);
CREATE INDEX IF NOT EXISTS idx_activity_events_entity
    ON activity_events(entity_kind, entity_id, occurred_at DESC);

CREATE TABLE IF NOT EXISTS price_master_imports (
    id BIGSERIAL PRIMARY KEY,
    import_id TEXT NOT NULL UNIQUE,
    master_type TEXT NOT NULL,
    source_type TEXT NOT NULL,
    original_filename TEXT,
    stored_path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    size_bytes INTEGER,
    imported_at TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 0,
    validation_status TEXT NOT NULL,
    validation_summary_json TEXT,
    activated_at TEXT,
    deactivated_at TEXT,
    schema_version INTEGER NOT NULL,
    file_bytes BYTEA
);
CREATE INDEX IF NOT EXISTS idx_price_master_imports_active ON price_master_imports(master_type, active);
CREATE INDEX IF NOT EXISTS idx_price_master_imports_sha ON price_master_imports(master_type, sha256);

CREATE TABLE IF NOT EXISTS manufacturer_price_sources (
    id BIGSERIAL PRIMARY KEY,
    source_key TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    source_url TEXT NOT NULL DEFAULT '',
    enabled INTEGER NOT NULL DEFAULT 0,
    parser_profile TEXT NOT NULL,
    lifecycle_status TEXT NOT NULL,
    last_checked_at TEXT,
    last_check_status TEXT,
    last_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    updated_by TEXT,
    row_version INTEGER NOT NULL DEFAULT 1
);

-- Audit / locking columns for databases created before v1.1.
ALTER TABLE technical_cases ADD COLUMN IF NOT EXISTS created_by TEXT;
ALTER TABLE technical_cases ADD COLUMN IF NOT EXISTS updated_by TEXT;
ALTER TABLE technical_cases ADD COLUMN IF NOT EXISTS row_version INTEGER NOT NULL DEFAULT 1;
ALTER TABLE technical_cases ADD COLUMN IF NOT EXISTS case_lifecycle_status TEXT NOT NULL DEFAULT 'ACTIVE';
ALTER TABLE technical_cases ADD COLUMN IF NOT EXISTS close_reason TEXT;
ALTER TABLE technical_cases ADD COLUMN IF NOT EXISTS closed_at TEXT;
ALTER TABLE technical_cases ADD COLUMN IF NOT EXISTS closed_by TEXT;
ALTER TABLE technical_cases ADD COLUMN IF NOT EXISTS close_memo TEXT;
ALTER TABLE quote_drafts ADD COLUMN IF NOT EXISTS created_by TEXT;
ALTER TABLE quote_drafts ADD COLUMN IF NOT EXISTS updated_by TEXT;
ALTER TABLE quote_drafts ADD COLUMN IF NOT EXISTS row_version INTEGER NOT NULL DEFAULT 1;
ALTER TABLE approved_quote_snapshots ADD COLUMN IF NOT EXISTS approved_by TEXT;
ALTER TABLE activity_events ADD COLUMN IF NOT EXISTS actor_email TEXT;
ALTER TABLE price_master_imports ADD COLUMN IF NOT EXISTS file_bytes BYTEA;

-- The app connects server-side with DATABASE_URL. Block the public Supabase REST API (anon key)
-- from these tables without adding row-level policies.
REVOKE ALL ON customers, technical_cases, technical_case_response_revisions, quote_drafts,
    approved_quote_snapshots, activity_events, price_master_imports, manufacturer_price_sources
    FROM anon, authenticated;
