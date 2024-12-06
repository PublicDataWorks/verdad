CREATE INDEX idx_snippets_title_english ON snippets USING pgroonga ((title ->> 'english'));
CREATE INDEX idx_snippets_title_spanish ON snippets USING pgroonga ((title ->> 'spanish'));

CREATE INDEX idx_snippets_summary_english ON snippets USING pgroonga ((summary ->> 'english'));
CREATE INDEX idx_snippets_summary_spanish ON snippets USING pgroonga ((summary ->> 'spanish'));

CREATE INDEX idx_snippets_explanation_english ON snippets USING pgroonga ((explanation ->> 'english'));
CREATE INDEX idx_snippets_explanation_spanish ON snippets USING pgroonga ((explanation ->> 'spanish'));
