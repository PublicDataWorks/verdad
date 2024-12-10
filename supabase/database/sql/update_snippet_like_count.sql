CREATE OR REPLACE FUNCTION update_snippet_like_count()
RETURNS TRIGGER AS $$
BEGIN
    UPDATE snippets
    SET 
        like_count = (
            SELECT COUNT(*)
            FROM user_like_snippets
            WHERE snippet = COALESCE(NEW.snippet, OLD.snippet)
            AND value = 1
        ),
        user_last_activity = NOW()
    WHERE id = COALESCE(NEW.snippet, OLD.snippet);
    
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;
