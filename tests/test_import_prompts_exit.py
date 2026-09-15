"""The explicit-version import must report failures through its exit status (no database)."""

import os
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for path in (REPO_ROOT, os.path.join(REPO_ROOT, "src")):
    if path not in sys.path:
        sys.path.insert(0, path)

from src.scripts import import_prompts_to_db as ipd  # noqa: E402


class FakeResponse:
    data = {"id": "row-1"}


class FakeClient:
    def __init__(self, fail: bool):
        self.fail = fail

    def rpc(self, name, params):
        return self

    def execute(self):
        if self.fail:
            raise RuntimeError("rpc failed")
        return FakeResponse()


@pytest.fixture
def one_entry(monkeypatch):
    monkeypatch.chdir(REPO_ROOT)  # PROMPT_MAPPING paths are relative to the repo root
    monkeypatch.setenv("SUPABASE_URL", "http://localhost")
    monkeypatch.setenv("SUPABASE_KEY", "test-key")
    return next(iter(ipd.PROMPT_MAPPING))


def test_import_prompts_returns_zero_when_every_entry_imports(one_entry, monkeypatch):
    monkeypatch.setattr(ipd, "_create_client", lambda: FakeClient(fail=False))
    assert ipd.import_prompts("9.9.9", "test", stages=[one_entry]) == 0


def test_import_prompts_returns_failure_count(one_entry, monkeypatch):
    monkeypatch.setattr(ipd, "_create_client", lambda: FakeClient(fail=True))
    assert ipd.import_prompts("9.9.9", "test", stages=[one_entry]) == 1


def test_main_exits_nonzero_when_an_import_fails(one_entry, monkeypatch):
    monkeypatch.setattr(ipd, "_create_client", lambda: FakeClient(fail=True))
    label = ipd._stage_label(one_entry)
    monkeypatch.setattr(sys, "argv", ["import_prompts_to_db.py", "import", "--version", "9.9.9", "--stages", label])
    with pytest.raises(SystemExit) as exc:
        ipd.main()
    assert exc.value.code == 1


def test_main_exits_zero_when_imports_succeed(one_entry, monkeypatch):
    monkeypatch.setattr(ipd, "_create_client", lambda: FakeClient(fail=False))
    label = ipd._stage_label(one_entry)
    monkeypatch.setattr(sys, "argv", ["import_prompts_to_db.py", "import", "--version", "9.9.9", "--stages", label])
    assert ipd.main() is None
