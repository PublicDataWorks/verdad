CREATE OR REPLACE FUNCTION update_snippet_hidden_status()
RETURNS TRIGGER AS $$
BEGIN

DECLARE
    negative_count INTEGER;
BEGIN
    -- Get count of negative likes after the new insertion
    SELECT COUNT(*) INTO negative_count
    FROM user_like_snippets uls 
    WHERE snippet = NEW.snippet AND uls.value = -1;

    -- Only proceed if this is a negative like (value = -1) and the total count is exactly 2
    IF NEW.value = -1 AND negative_count = 2 THEN
        -- Insert into user_hide_snippets if not already exists
        INSERT INTO user_hide_snippets (snippet)
        SELECT NEW.snippet
        WHERE NOT EXISTS (
            SELECT 1 
            FROM user_hide_snippets 
            WHERE snippet = NEW.snippet
        );
    END IF;
    
    RETURN NEW;
END;

END;
$$ LANGUAGE plpgsql;

-- Create the trigger
CREATE TRIGGER update_snippet_hidden_status_trigger
AFTER INSERT OR UPDATE ON user_like_snippets
FOR EACH ROW
EXECUTE FUNCTION update_snippet_hidden_status();
