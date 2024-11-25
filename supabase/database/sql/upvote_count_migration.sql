WITH upvote_counts AS (
    SELECT sl.snippet AS snippet_id,
           COUNT(lu.id) AS total_upvotes
    FROM snippet_labels sl
    LEFT JOIN label_upvotes lu ON lu.snippet_label = sl.id
    GROUP BY sl.snippet
)
UPDATE snippets s
SET upvote_count = COALESCE(uc.total_upvotes, 0)
FROM upvote_counts uc
WHERE s.id = uc.snippet_id;

CREATE INDEX idx_snippets_upvote_count ON snippets(upvote_count DESC);
