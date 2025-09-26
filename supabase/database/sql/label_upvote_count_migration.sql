WITH label_upvote_counts AS (
    SELECT
      snippet_label AS snippet_label_id,
      COUNT(*) AS total_upvotes
    FROM label_upvotes
    GROUP BY snippet_label
)
UPDATE snippet_labels sl
SET upvote_count = COALESCE(luc.total_upvotes, 0)
FROM label_upvote_counts luc
WHERE sl.id = luc.snippet_label_id;
