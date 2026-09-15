from unittest.mock import Mock

from processing_pipeline.processing_utils import postprocess_snippet, remove_stale_ai_labels, stale_ai_snippet_labels


def _row(row_id, text, text_spanish=None, is_ai=True, applied_by=None, upvotes=0):
    return {
        "id": row_id,
        "applied_by": applied_by,
        "upvote_count": upvotes,
        "label": {"id": f"l-{row_id}", "text": text, "text_spanish": text_spanish or text, "is_ai_suggested": is_ai},
    }


NEW_CATEGORIES = [{"english": "Election Fraud", "spanish": "Fraude electoral"}]


class TestStaleAiSnippetLabels:
    def test_removes_ai_label_no_longer_in_categories(self):
        rows = [_row(1, "Election Fraud"), _row(2, "Fabricated Event")]
        assert [r["id"] for r in stale_ai_snippet_labels(rows, NEW_CATEGORIES)] == [2]

    def test_matches_on_spanish_text_too(self):
        rows = [_row(1, "Some old English", text_spanish="Fraude electoral")]
        assert stale_ai_snippet_labels(rows, NEW_CATEGORIES) == []

    def test_never_touches_user_labels(self):
        rows = [
            _row(1, "Fabricated Event", is_ai=False),
            _row(2, "Fabricated Event", applied_by="user-uuid"),
            _row(3, "Fabricated Event", upvotes=2),
        ]
        assert stale_ai_snippet_labels(rows, NEW_CATEGORIES) == []

    def test_case_insensitive_match(self):
        assert stale_ai_snippet_labels([_row(1, "election fraud")], NEW_CATEGORIES) == []

    def test_empty_categories_removes_all_ai_labels(self):
        assert len(stale_ai_snippet_labels([_row(1, "A"), _row(2, "B", is_ai=False)], [])) == 1


class TestRemoveStaleAiLabels:
    def test_deletes_only_stale_rows(self):
        client = Mock()
        client.get_snippet_labels.return_value = [_row(1, "Election Fraud"), _row(2, "Old")]
        remove_stale_ai_labels(client, "snip", NEW_CATEGORIES)
        client.delete_snippet_label.assert_called_once_with(2)

    def test_postprocess_prunes_before_assigning_new_labels(self):
        client = Mock()
        client.get_snippet_labels.return_value = [_row(2, "Old")]
        client.create_new_label.return_value = {"id": "lbl"}

        postprocess_snippet(client, "snip", NEW_CATEGORIES)

        client.delete_snippet_label.assert_called_once_with(2)
        client.assign_label_to_snippet.assert_called_with(label_id="lbl", snippet_id="snip")
