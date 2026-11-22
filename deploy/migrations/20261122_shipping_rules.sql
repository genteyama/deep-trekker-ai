-- PORTAL-2A.3: Manual International Shipping Reference Master.
-- Idempotent: safe to re-run. Apply manually to Supabase after review; the app never creates
-- this table at runtime on PostgreSQL.

CREATE TABLE IF NOT EXISTS shipping_rules (
    id BIGSERIAL PRIMARY KEY,
    shipping_rule_id TEXT NOT NULL UNIQUE,
    shipping_type TEXT NOT NULL,
    destination_region TEXT NOT NULL,
    rate_usd NUMERIC(12, 2) NOT NULL CHECK (rate_usd > 0),
    currency TEXT NOT NULL DEFAULT 'USD',
    charge_basis TEXT NOT NULL,
    scope_type TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_reference TEXT,
    effective_from TEXT NOT NULL,
    status TEXT NOT NULL,
    notes TEXT,
    created_at TEXT NOT NULL,
    created_by TEXT
);
CREATE INDEX IF NOT EXISTS idx_shipping_rules_type ON shipping_rules(shipping_type);
CREATE INDEX IF NOT EXISTS idx_shipping_rules_region ON shipping_rules(destination_region);
CREATE INDEX IF NOT EXISTS idx_shipping_rules_scope ON shipping_rules(scope_type);
CREATE INDEX IF NOT EXISTS idx_shipping_rules_status ON shipping_rules(status);
-- At most one current APPROVED version per type / region / scope.
CREATE UNIQUE INDEX IF NOT EXISTS uq_shipping_rules_one_approved
    ON shipping_rules(shipping_type, destination_region, scope_type) WHERE status = 'APPROVED';

-- Initial standard GLOBAL rates confirmed as of 2026-10-23. created_at = registration time (UTC).
INSERT INTO shipping_rules (
    shipping_rule_id, shipping_type, destination_region, rate_usd, currency, charge_basis, scope_type,
    source_type, source_reference, effective_from, status, notes, created_at, created_by
)
SELECT seed.shipping_rule_id, seed.shipping_type, 'GLOBAL', seed.rate_usd, 'USD', seed.charge_basis, 'STANDARD',
       'MANUAL', 'Manual shipping reference / confirmed as of 2026-10-23', '2026-10-23', 'APPROVED', NULL,
       to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"+00:00"'), 'system:PORTAL-2A.3 seed'
FROM (VALUES
    ('ship-std-global-large_box-20261023-seed', 'LARGE_BOX', 2922.15, 'PER_PARCEL'),
    ('ship-std-global-small_box-20261023-seed', 'SMALL_BOX', 1356.00, 'PER_PARCEL'),
    ('ship-std-global-pipe_trekker-20261023-seed', 'PIPE_TREKKER', 8828.15, 'PER_ORDER_BASE')
) AS seed(shipping_rule_id, shipping_type, rate_usd, charge_basis)
ON CONFLICT DO NOTHING;

REVOKE ALL ON shipping_rules FROM anon, authenticated;
