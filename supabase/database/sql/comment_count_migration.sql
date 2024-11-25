UPDATE snippets s
SET comment_count = (
    SELECT COUNT(*)
    FROM comments c
    WHERE c.room_id = s.id
    and deleted_at is null
);

CREATE INDEX idx_snippets_comment_count ON snippets(comment_count DESC);
