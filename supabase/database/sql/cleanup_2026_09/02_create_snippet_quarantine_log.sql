-- cleanup_2026_09 / step 02: audit log for quarantined snippets.
--
-- One row per (snippet, batch). previous_status is what the snippet had before
-- it was set to 'Quarantined' so 05_quarantine_rollback.sql can restore it
-- exactly. restored_at is set by the rollback; a row with restored_at IS NULL
-- is a currently quarantined snippet for that batch.
--
-- snippet is deliberately NOT a foreign key: the pipeline deletes snippets
-- (SupabaseClient.delete_snippet, used by the Stage 2 redo flow), and a
-- REFERENCES ... ON DELETE CASCADE would erase the audit row with the snippet.
-- An audit log must outlive what it describes, so the column is a plain
-- NOT NULL uuid; 05/09 join it to snippets and simply skip ids that no longer exist.
--
-- Access pattern follows public.user_hide_snippets / user_like_snippets in this
-- project: RLS enabled with NO policies, so only service_role (which bypasses
-- RLS) and the postgres owner can read or write it. The anon/authenticated
-- roles get no grant. (kb_entries uses explicit policies instead because the
-- web app reads it; nothing in the app reads this log.)
CREATE TABLE IF NOT EXISTS public.snippet_quarantine_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    snippet         UUID NOT NULL,   -- no FK on purpose, see header
    previous_status public.processing_status NOT NULL,
    reason          TEXT NOT NULL,
    batch           TEXT NOT NULL,
    quarantined_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    restored_at     TIMESTAMPTZ NULL,
    UNIQUE (snippet, batch)
);

COMMENT ON TABLE public.snippet_quarantine_log IS
    'cleanup_2026_09: which snippets were moved to status Quarantined, why, in which batch, and whether they were restored.';

-- UNIQUE (snippet, batch) already gives a btree on (snippet, batch); the two
-- single-column indexes below serve rollback (by batch) and point lookups.
CREATE INDEX IF NOT EXISTS idx_snippet_quarantine_log_snippet
    ON public.snippet_quarantine_log (snippet);
CREATE INDEX IF NOT EXISTS idx_snippet_quarantine_log_batch
    ON public.snippet_quarantine_log (batch);

ALTER TABLE public.snippet_quarantine_log ENABLE ROW LEVEL SECURITY;
-- No policies on purpose: service_role only.
GRANT ALL ON TABLE public.snippet_quarantine_log TO service_role;
