CREATE TRIGGER update_like_count
AFTER INSERT OR UPDATE OR DELETE ON user_like_snippets
FOR EACH ROW
EXECUTE FUNCTION update_snippet_like_count();
