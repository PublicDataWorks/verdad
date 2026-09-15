import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "upload_eval_artifacts", Path(__file__).resolve().parents[1] / "scripts" / "ci" / "upload_eval_artifacts.py"
)
upload_eval_artifacts = importlib.util.module_from_spec(spec)
spec.loader.exec_module(upload_eval_artifacts)


class FakeS3:
    def __init__(self):
        self.calls = []

    def upload_file(self, path, bucket, key, ExtraArgs=None):
        self.calls.append((path, bucket, key, ExtraArgs))


def test_upload_keys_files_under_prefix_with_content_types(tmp_path):
    report = tmp_path / "eval-report-set.md"
    results = tmp_path / "eval-results-set.json"
    report.write_text("# report")
    results.write_text("{}")
    s3 = FakeS3()

    keys = upload_eval_artifacts.upload([str(report), str(results)], "bucket", "prompt-eval/abc123/", s3)

    assert keys == ["prompt-eval/abc123/eval-report-set.md", "prompt-eval/abc123/eval-results-set.json"]
    assert s3.calls[0][1:] == ("bucket", keys[0], {"ContentType": "text/markdown"})
    assert s3.calls[1][1:] == ("bucket", keys[1], {"ContentType": "application/json"})
