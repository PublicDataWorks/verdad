UPDATE snippets s
SET comment_count = (
    SELECT COUNT(*)
    FROM comments c
    WHERE c.room_id = s.id
    and deleted_at is null
);
