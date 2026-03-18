-- Downvote Review Queue
-- Tracks downvoted snippets awaiting KB review.
-- When a user downvotes a snippet (value=-1 in user_like_snippets),
-- a trigger queues it here for automated review and KB entry creation.

CREATE TABLE IF NOT EXISTS public.downvote_review_queue (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    snippet_id UUID NOT NULL REFERENCES public.snippets(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'processing', 'completed', 'error')),
    downvoted_by UUID,
    downvoted_at TIMESTAMPTZ DEFAULT now(),
    processed_at TIMESTAMPTZ,
    kb_entries_created INTEGER DEFAULT 0,
    error_message TEXT,
    created_at TIMESTAMPTZ DEFAULT now(),
    CONSTRAINT unique_snippet_in_queue UNIQUE (snippet_id)
);

CREATE INDEX IF NOT EXISTS idx_downvote_review_queue_status
    ON public.downvote_review_queue(status);

-- RLS
ALTER TABLE public.downvote_review_queue ENABLE ROW LEVEL SECURITY;

GRANT ALL ON TABLE public.downvote_review_queue TO service_role;
GRANT SELECT ON TABLE public.downvote_review_queue TO authenticated;

CREATE POLICY "Enable full access for service role"
    ON public.downvote_review_queue FOR ALL TO service_role USING (true);

CREATE POLICY "Enable read access for authenticated users"
    ON public.downvote_review_queue FOR SELECT TO authenticated USING (true);
