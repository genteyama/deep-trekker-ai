-- PORTAL-3A: quote integrity (official quote number fixed at approval).
-- Idempotent: safe to re-run. Apply manually to Supabase after review, BEFORE deploying the
-- PORTAL-3A code (the app writes this column when a quote is approved).
--
-- Approver, approval time, confirmations and revision lineage need no schema change: they live in
-- the existing approved_quote_snapshots.approved_by / payload_json and quote_drafts
-- parent_quote_id / source_quote_id / relation_type / status columns.

ALTER TABLE approved_quote_snapshots ADD COLUMN IF NOT EXISTS official_quote_number TEXT;

-- One official quote number belongs to exactly one approved snapshot. Existing rows stay NULL and
-- are not affected by the partial index.
CREATE UNIQUE INDEX IF NOT EXISTS uq_approved_quote_snapshots_official_number
    ON approved_quote_snapshots(official_quote_number)
    WHERE official_quote_number IS NOT NULL;
