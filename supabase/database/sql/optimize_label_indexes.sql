-- Indexes to optimize the CTE-based label aggregation query

-- 1. Additional index for label_upvotes to optimize the LATERAL join
CREATE INDEX IF NOT EXISTS idx_label_upvotes_snippet_label_upvoted_by
ON public.label_upvotes USING btree (snippet_label, upvoted_by);

-- 2. Index for main snippets filtering
CREATE INDEX IF NOT EXISTS idx_snippets_status_confidence
ON public.snippets USING btree (status, (((confidence_scores->>'overall'))::INTEGER))
WHERE (status = 'Processed'::processing_status);
