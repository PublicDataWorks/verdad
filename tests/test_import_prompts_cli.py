"""Tests for the import / list / diff commands of src/scripts/import_prompts_to_db.py (no database access)."""

import json
import os
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.processing_pipeline.constants import PromptStage
from src.processing_pipeline.stage_1.constants import Stage1SubStage
from src.scripts import import_prompts_to_db as mod

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STAGE_3 = (PromptStage.STAGE_3, None)
INITIAL_DETECTION = (PromptStage.STAGE_1, Stage1SubStage.INITIAL_DETECTION)


@pytest.fixture(autouse=True)
def repo_root_cwd(monkeypatch):
    """PROMPT_MAPPING paths are relative to the repository root."""
    monkeypatch.chdir(REPO_ROOT)


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
    monkeypatch.setenv("SUPABASE_KEY", "test-key")


def stage_3_row(**overrides):
    local = mod.load_local_prompt(mod.PROMPT_MAPPING[STAGE_3])
    row = {
        "id": "row-3",
        "stage": "stage_3",
        "sub_stage": None,
        "version": "1.0.0",
        "description": "live",
        "created_at": "2026-01-02T03:04:05+00:00",
        **local,
    }
    row.update(overrides)
    return row


def active_client(rows):
    client = MagicMock()
    client.table.return_value.select.return_value.eq.return_value.execute.return_value = SimpleNamespace(data=rows)
    return client


def list_client(rows):
    client = MagicMock()
    query = client.table.return_value.select.return_value.order.return_value.order.return_value.order.return_value
    query.execute.return_value = SimpleNamespace(data=rows)
    return client


class TestValidation:
    def test_validate_version(self):
        assert mod.validate_version("1.2.3")
        assert not mod.validate_version("1.2")
        assert not mod.validate_version("v1.2.3")

    def test_validate_path_safety(self):
        assert mod.validate_path_safety("prompts/stage_3/system_instruction.md")
        assert not mod.validate_path_safety("prompts/../README.md")
        assert not mod.validate_path_safety("/etc/passwd")

    def test_validate_description_strips_and_limits(self):
        assert mod.validate_description("  hello  ") == "hello"
        with pytest.raises(ValueError, match="Description too long"):
            mod.validate_description("x" * (mod.MAX_DESCRIPTION_LENGTH + 1))

    def test_stage_labels_round_trip(self):
        assert mod._stage_label(STAGE_3) == "stage_3"
        assert mod._stage_label(INITIAL_DETECTION) == "stage_1/initial_detection"
        for key in mod.PROMPT_MAPPING:
            assert mod._parse_stage_label(mod._stage_label(key)) == key
        assert mod._parse_stage_label("stage_9") is None

    def test_check_files_exist_on_repo_prompts(self):
        all_valid, missing, unsafe = mod.check_files_exist(list(mod.PROMPT_MAPPING))
        assert (all_valid, missing, unsafe) == (True, [], [])
        assert mod.check_files_exist([("unknown", None)]) == (True, [], [])

    def test_check_files_exist_reports_missing_and_unsafe(self, monkeypatch):
        monkeypatch.setitem(
            mod.PROMPT_MAPPING,
            STAGE_3,
            {"system_instruction": "prompts/stage_3/nope.md", "user_prompt": "/etc/passwd"},
        )
        all_valid, missing, unsafe = mod.check_files_exist([STAGE_3])
        assert not all_valid
        assert missing == ["stage_3/system_instruction: prompts/stage_3/nope.md"]
        assert unsafe == ["stage_3/user_prompt: /etc/passwd"]


class TestClient:
    def test_create_client_requires_env(self, monkeypatch):
        monkeypatch.delenv("SUPABASE_URL", raising=False)
        monkeypatch.delenv("SUPABASE_KEY", raising=False)
        with pytest.raises(ValueError, match="SUPABASE_URL and SUPABASE_KEY"):
            mod._create_client()

    def test_create_client_uses_env(self, env, monkeypatch):
        create = MagicMock(return_value="client")
        monkeypatch.setattr(mod, "create_client", create)
        assert mod._create_client() == "client"
        create.assert_called_once_with("https://test.supabase.co", "test-key")

    def test_fetch_active_prompts_keys_rows_by_stage(self):
        rows = [{"stage": "stage_3", "sub_stage": None}, {"stage": "stage_1", "sub_stage": "initial_detection"}]
        assert mod.fetch_active_prompts(active_client(rows)) == {
            ("stage_3", None): rows[0],
            ("stage_1", "initial_detection"): rows[1],
        }
        assert mod.fetch_active_prompts(active_client(None)) == {}


class TestDiff:
    def test_field_text_and_unified_diff(self, capsys):
        assert mod._field_text("user_prompt", None) == "\n"
        assert mod._field_text("user_prompt", "a\n") == "a\n"
        assert mod._field_text("output_schema", '{"b": 1, "a": 2}') == '{\n  "a": 2,\n  "b": 1\n}\n'
        mod.print_field_diff("stage_3", "user_prompt", "prompts/x.md", "new text", "old text")
        out = capsys.readouterr().out
        assert "--- db:stage_3/user_prompt" in out
        assert "+++ local:prompts/x.md" in out
        assert "-old text" in out and "+new text" in out

    def test_diff_returns_2_when_db_unreachable(self, monkeypatch, capsys):
        monkeypatch.setattr(mod, "_create_client", MagicMock(side_effect=ValueError("no env")))
        assert mod.diff_prompts() == 2
        assert "could not load active prompt versions: no env" in capsys.readouterr().err

    def test_diff_in_sync(self, monkeypatch, capsys):
        monkeypatch.setattr(mod, "_create_client", MagicMock(return_value=active_client([stage_3_row()])))
        assert mod.diff_prompts(stages=[STAGE_3]) == 0
        assert capsys.readouterr().out.strip() == "stage_3: in sync [db v1.0.0, 2026-01-02]"

    def test_diff_reports_drift_and_missing_rows(self, monkeypatch, capsys):
        row = stage_3_row(user_prompt="something else", created_at=None)
        monkeypatch.setattr(mod, "_create_client", MagicMock(return_value=active_client([row])))
        assert mod.diff_prompts(stages=[STAGE_3, INITIAL_DETECTION], show_diff=True) == 1
        out = capsys.readouterr().out
        assert "stage_3: differs (user_prompt) [db v1.0.0, ]" in out
        assert "stage_1/initial_detection: no active version in db" in out
        assert "--- db:stage_3/user_prompt" in out
        assert "+++ local:prompts/stage_3/analysis_prompt.md" in out

    def test_diff_defaults_to_every_mapping_entry(self, monkeypatch, capsys):
        monkeypatch.setattr(mod, "_create_client", MagicMock(return_value=active_client([])))
        assert mod.diff_prompts() == 1
        assert len(capsys.readouterr().out.strip().splitlines()) == len(mod.PROMPT_MAPPING)


class TestImport:
    def test_rejects_bad_version(self):
        with pytest.raises(ValueError, match="Invalid version format"):
            mod.import_prompts("1.0", "desc")

    def test_rejects_unsafe_paths(self, monkeypatch, capsys):
        monkeypatch.setitem(mod.PROMPT_MAPPING, STAGE_3, {"user_prompt": "/etc/passwd"})
        with pytest.raises(ValueError, match="unsafe file paths"):
            mod.import_prompts("1.0.0", "desc", stages=[STAGE_3])
        assert "outside the allowed directory" in capsys.readouterr().out

    def test_rejects_missing_files(self, monkeypatch, capsys):
        monkeypatch.setitem(mod.PROMPT_MAPPING, STAGE_3, {"user_prompt": "prompts/stage_3/nope.md"})
        with pytest.raises(FileNotFoundError, match="missing files"):
            mod.import_prompts("1.0.0", "desc", stages=[STAGE_3])
        assert "prompts/stage_3/nope.md" in capsys.readouterr().out

    def test_requires_env_even_for_dry_run(self, monkeypatch):
        monkeypatch.delenv("SUPABASE_URL", raising=False)
        monkeypatch.delenv("SUPABASE_KEY", raising=False)
        with pytest.raises(ValueError, match="SUPABASE_URL and SUPABASE_KEY"):
            mod.import_prompts("1.0.0", "desc", dry_run=True)

    def test_dry_run_previews_without_a_client(self, env, monkeypatch, capsys):
        create = MagicMock()
        monkeypatch.setattr(mod, "create_client", create)
        mod.import_prompts("1.0.0", "desc", stages=[STAGE_3, INITIAL_DETECTION], dry_run=True)
        create.assert_not_called()
        out = capsys.readouterr().out
        assert "DRY RUN MODE" in out
        assert "Would create version 1.0.0 for stage_3" in out
        assert "Would deactivate existing active version" in out
        assert "2 entries previewed" in out

    def test_import_calls_upsert_rpc(self, env, monkeypatch, capsys):
        client = MagicMock()
        client.rpc.return_value.execute.return_value = SimpleNamespace(data={"id": "new-row"})
        monkeypatch.setattr(mod, "create_client", MagicMock(return_value=client))
        mod.import_prompts("2.0.0", "  new  ", stages=[INITIAL_DETECTION])
        name, payload = client.rpc.call_args.args
        assert name == "upsert_prompt_version"
        assert payload["p_stage"] == "stage_1"
        assert payload["p_sub_stage"] == "initial_detection"
        assert payload["p_version"] == "2.0.0"
        assert payload["p_description"] == "new"
        assert payload["p_set_active"] is True
        assert payload["p_system_instruction"] == mod.read_file(
            "prompts/stage_1/preprocess/initial_detection_system_instruction.md"
        )
        assert payload["p_output_schema"] == mod.read_json(
            "prompts/stage_1/preprocess/initial_detection_output_schema.json"
        )
        out = capsys.readouterr().out
        assert "Created prompt version: new-row" in out
        assert "Set as active version for stage_1/initial_detection" in out
        assert "Success: 1, Errors: 0" in out

    def test_import_counts_errors(self, env, monkeypatch, capsys):
        client = MagicMock()
        client.rpc.return_value.execute.side_effect = [SimpleNamespace(data=None), RuntimeError("boom")]
        monkeypatch.setattr(mod, "create_client", MagicMock(return_value=client))
        mod.import_prompts("1.0.0", "desc", set_active=False, stages=[STAGE_3, INITIAL_DETECTION])
        out = capsys.readouterr().out
        assert "No data returned for stage_3" in out
        assert "Error creating prompt version for stage_1/initial_detection: boom" in out
        assert "Success: 0, Errors: 2" in out
        assert client.rpc.call_args.args[1]["p_set_active"] is False

    def test_import_skips_unknown_keys(self, env, monkeypatch, capsys):
        monkeypatch.setattr(mod, "create_client", MagicMock())
        mod.import_prompts("1.0.0", "desc", stages=[("stage_9", None)])
        out = capsys.readouterr().out
        assert "Unknown key" in out
        assert "Success: 0, Errors: 0" in out


class TestList:
    def test_list_empty(self, monkeypatch, capsys):
        monkeypatch.setattr(mod, "_create_client", MagicMock(return_value=list_client([])))
        mod.list_versions()
        assert "No prompt versions found" in capsys.readouterr().out

    def test_list_prints_rows(self, monkeypatch, capsys):
        rows = [
            {
                "stage": "stage_1",
                "sub_stage": "initial_detection",
                "version": "1.0.0",
                "is_active": True,
                "description": "a",
            },
            {"stage": "stage_3", "sub_stage": None, "version": "0.9.0", "is_active": False, "description": None},
        ]
        monkeypatch.setattr(mod, "_create_client", MagicMock(return_value=list_client(rows)))
        mod.list_versions()
        out = capsys.readouterr().out
        assert "stage_1         initial_detection              1.0.0      Yes" in out
        assert "stage_3         -                              0.9.0      No" in out


class TestMain:
    def test_import_command(self, monkeypatch):
        import_prompts = MagicMock()
        monkeypatch.setattr(mod, "import_prompts", import_prompts)
        argv = [
            "prog",
            "import",
            "--version",
            "1.2.0",
            "--description",
            "d",
            "--no-active",
            "--dry-run",
            "--stages",
            "stage_3",
        ]
        monkeypatch.setattr(sys, "argv", argv)
        mod.main()
        import_prompts.assert_called_once_with(
            version="1.2.0", description="d", set_active=False, stages=[STAGE_3], dry_run=True
        )

    def test_import_command_defaults(self, monkeypatch):
        import_prompts = MagicMock()
        monkeypatch.setattr(mod, "import_prompts", import_prompts)
        monkeypatch.setattr(sys, "argv", ["prog", "import", "--version", "1.2.0"])
        mod.main()
        import_prompts.assert_called_once_with(
            version="1.2.0", description="Imported from files", set_active=True, stages=None, dry_run=False
        )

    def test_list_command(self, monkeypatch):
        list_versions = MagicMock()
        monkeypatch.setattr(mod, "list_versions", list_versions)
        monkeypatch.setattr(sys, "argv", ["prog", "list"])
        mod.main()
        list_versions.assert_called_once_with()

    def test_diff_command_exits_with_status(self, monkeypatch):
        diff_prompts = MagicMock(return_value=1)
        monkeypatch.setattr(mod, "diff_prompts", diff_prompts)
        monkeypatch.setattr(sys, "argv", ["prog", "diff", "--show-diff", "--stages", "stage_1/initial_detection"])
        with pytest.raises(SystemExit) as exc:
            mod.main()
        assert exc.value.code == 1
        diff_prompts.assert_called_once_with(stages=[INITIAL_DETECTION], show_diff=True)

    def test_rejects_unknown_stage(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["prog", "diff", "--stages", "stage_9"])
        with pytest.raises(SystemExit) as exc:
            mod.main()
        assert exc.value.code == 2

    def test_no_command_prints_help(self, monkeypatch, capsys):
        monkeypatch.setattr(sys, "argv", ["prog"])
        mod.main()
        assert "usage:" in capsys.readouterr().out


def test_read_json_and_read_file(tmp_path):
    (tmp_path / "a.json").write_text(json.dumps({"k": 1}), encoding="utf-8")
    (tmp_path / "a.md").write_text("text", encoding="utf-8")
    assert mod.read_json(str(tmp_path / "a.json")) == {"k": 1}
    assert mod.read_file(str(tmp_path / "a.md")) == "text"
