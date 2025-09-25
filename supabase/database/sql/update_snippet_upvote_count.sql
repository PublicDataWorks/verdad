CREATE OR REPLACE FUNCTION update_snippet_upvote_count()
RETURNS TRIGGER AS $$
DECLARE
    snippet_id UUID;
    snippet_label_id UUID;
BEGIN
    snippet_label_id := COALESCE(NEW.snippet_label, OLD.snippet_label);

    UPDATE snippet_labels
    SET upvote_count = (
        SELECT COUNT(*)
        FROM label_upvotes
        WHERE snippet_label = snippet_label_id
    )
    WHERE id = snippet_label_id
    RETURNING snippet INTO snippet_id;

    IF snippet_id IS NOT NULL THEN
        UPDATE snippets
        SET 
            upvote_count = (
                SELECT COUNT(*)
                FROM label_upvotes lu
                JOIN snippet_labels sl ON lu.snippet_label = sl.id
                WHERE sl.snippet = snippet_id
            ),
            user_last_activity = NOW()
        WHERE id = snippet_id;
    END IF;
    
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;
