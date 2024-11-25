UPDATE snippets s
SET like_count = (
    SELECT COUNT(*)
    FROM user_like_snippets uls
    WHERE uls.snippet = s.id
    AND uls.value = 1
);

CREATE INDEX idx_snippets_like_count ON snippets(like_count DESC);
