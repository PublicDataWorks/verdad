CREATE OR REPLACE FUNCTION update_snippet_comment_count() 
RETURNS TRIGGER AS $$
BEGIN
    UPDATE snippets
    SET 
        comment_count = (
            SELECT COUNT(*)
            FROM comments 
            WHERE room_id = COALESCE(NEW.room_id, OLD.room_id)
        ),
        user_last_activity = NOW()
    WHERE id = COALESCE(NEW.room_id, OLD.room_id);
    
    RETURN NULL;
END;

$$ LANGUAGE plpgsql;
