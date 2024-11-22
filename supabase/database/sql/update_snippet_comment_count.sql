CREATE OR REPLACE FUNCTION update_snippet_comment_count()
RETURNS TRIGGER AS $$
BEGIN
    -- For INSERT
    IF (TG_OP = 'INSERT') THEN
        UPDATE snippets
        SET comment_count = comment_count + 1
        WHERE id = NEW.room_id;
    
    -- For DELETE
    ELSIF (TG_OP = 'DELETE') THEN
        UPDATE snippets
        SET comment_count = comment_count - 1
        WHERE id = OLD.room_id;
    END IF;
    
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;
