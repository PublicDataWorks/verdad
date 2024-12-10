CREATE OR REPLACE FUNCTION update_snippet_upvote_count()
RETURNS TRIGGER AS $$
DECLARE
    snippet_id UUID;
BEGIN
    SELECT snippet INTO snippet_id
    FROM snippet_labels
    WHERE id = COALESCE(NEW.snippet_label, OLD.snippet_label);

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
