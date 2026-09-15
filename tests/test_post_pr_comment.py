import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "post_pr_comment", Path(__file__).resolve().parents[1] / "scripts" / "ci" / "post_pr_comment.py"
)
post_pr_comment = importlib.util.module_from_spec(spec)
spec.loader.exec_module(post_pr_comment)

MARKER = "<!-- prompt-evaluation-report -->"


class FakeGitHub:
    def __init__(self, comments):
        self.comments = comments
        self.calls = []

    def __call__(self, method, url, token, payload=None):
        self.calls.append((method, url, payload))
        return self.comments if method == "GET" else {}


def test_find_comment_id_matches_marker_only():
    comments = [{"id": 1, "body": "unrelated"}, {"id": 2, "body": f"{MARKER}\nold report"}, {"id": 3, "body": None}]
    assert post_pr_comment.find_comment_id(comments, MARKER) == 2
    assert post_pr_comment.find_comment_id(comments[:1], MARKER) is None


def test_upsert_creates_when_no_marker_comment():
    github = FakeGitHub([{"id": 1, "body": "unrelated"}])
    result = post_pr_comment.upsert_comment("org/repo", 7, MARKER, "new report", "tok", request=github)
    assert result == "created"
    url = f"{post_pr_comment.API}/repos/org/repo/issues/7/comments"
    assert github.calls[-1] == ("POST", url, {"body": "new report"})


def test_upsert_updates_existing_marker_comment():
    github = FakeGitHub([{"id": 42, "body": f"{MARKER}\nold"}])
    result = post_pr_comment.upsert_comment("org/repo", 7, MARKER, "new report", "tok", request=github)
    assert result == "updated"
    url = f"{post_pr_comment.API}/repos/org/repo/issues/comments/42"
    assert github.calls[-1] == ("PATCH", url, {"body": "new report"})
