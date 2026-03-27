-- Trigger: On downvote, immediately hide the snippet and queue a KB review.
-- Fires on INSERT into user_like_snippets when value = -1.
-- This replaces the old behavior of waiting for 2 downvotes to hide.

CREATE OR REPLACE FUNCTION on_downvote_queue_review()
RETURNS TRIGGER AS $$
BEGIN
    -- Only process downvotes (value = -1)
    IF NEW.value = -1 THEN
        -- Immediately hide the snippet
        INSERT INTO user_hide_snippets (snippet)
        VALUES (NEW.snippet)
        ON CONFLICT (snippet) DO NOTHING;

        -- Queue for KB review (UNIQUE constraint prevents duplicates)
        INSERT INTO downvote_review_queue (snippet_id, downvoted_by, downvoted_at)
        VALUES (NEW.snippet, NEW."user", now())
        ON CONFLICT (snippet_id) DO NOTHING;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER on_downvote_queue_review_trigger
AFTER INSERT ON user_like_snippets
FOR EACH ROW
EXECUTE FUNCTION on_downvote_queue_review();
