CREATE TRIGGER update_upvote_count
AFTER INSERT OR DELETE ON label_upvotes
FOR EACH ROW
EXECUTE FUNCTION update_snippet_upvote_count();
