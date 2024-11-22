CREATE OR REPLACE FUNCTION update_snippet_like_count()
RETURNS TRIGGER AS $$
BEGIN
    -- Update the like count for the affected snippet
    UPDATE snippets
    SET like_count = (
        SELECT COUNT(*)
        FROM user_like_snippets
        WHERE snippet = COALESCE(NEW.snippet, OLD.snippet)
        AND value = 1
    )
    WHERE id = COALESCE(NEW.snippet, OLD.snippet);
    
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;
