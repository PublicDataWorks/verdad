CREATE OR REPLACE FUNCTION update_snippet_hidden_status()
RETURNS TRIGGER AS $$
BEGIN
    IF (
        SELECT COUNT(*)
        FROM user_like_snippets
        WHERE snippet = NEW.snippet
    ) = 2
    THEN
        INSERT INTO user_hide_snippets (
            snippet,
        )
        SELECT 
            NEW.snippet
        WHERE NOT EXISTS (
            SELECT 1 
            FROM user_hide_snippets 
            WHERE snippet = NEW.snippet
        );
    END IF;
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Create the trigger
CREATE TRIGGER update_snippet_hidden_status_trigger
AFTER INSERT ON user_like_snippets
FOR EACH ROW
EXECUTE FUNCTION update_snippet_hidden_status();
