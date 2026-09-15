import importlib.util
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_stage.py"


@pytest.fixture(scope="module")
def run_stage():
    spec = importlib.util.spec_from_file_location("run_stage", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestParseArgs:
    def test_stage_is_required(self, run_stage):
        with pytest.raises(SystemExit):
            run_stage.parse_args([])

    def test_stage_1_defaults(self, run_stage):
        args = run_stage.parse_args(["--stage", "1"])
        assert (args.stage, args.audio_file_id, args.limit) == (1, None, 1)

    def test_snippet_ids_repeatable(self, run_stage):
        args = run_stage.parse_args(["--stage", "3", "--snippet-id", "a", "--snippet-id", "b", "--skip-review"])
        assert (args.snippet_ids, args.skip_review) == (["a", "b"], True)

    @pytest.mark.parametrize(
        "argv",
        [
            ["--stage", "2", "--audio-file-id", "x"],
            ["--stage", "3", "--limit", "2"],
            ["--stage", "1", "--snippet-id", "x"],
            ["--stage", "4", "--skip-review"],
            ["--stage", "6"],
            ["--stage", "1", "--limit", "0"],
            ["--stage", "1", "--limit", "-1"],
            ["--stage", "1", "--audio-file-id", "x", "--limit", "2"],
            ["--stage", "1", "--context-before-seconds", "10"],
            ["--stage", "3", "--context-after-seconds", "30"],
            ["--stage", "5", "--context-before-seconds", "10"],
        ],
    )
    def test_rejects_options_for_other_stages(self, run_stage, argv):
        with pytest.raises(SystemExit) as excinfo:
            run_stage.parse_args(argv)
        assert excinfo.value.code == 2

    @pytest.mark.parametrize(
        ("argv", "expected"),
        [
            (["--stage", "1", "--limit", "0"], "--limit must be a positive integer"),
            (["--stage", "1", "--audio-file-id", "x", "--limit", "2"], "--limit does not apply with --audio-file-id"),
            (["--stage", "3", "--context-before-seconds", "10"], "only apply to --stage 2"),
        ],
    )
    def test_rejection_message_explains_the_conflict(self, run_stage, capsys, argv, expected):
        with pytest.raises(SystemExit):
            run_stage.parse_args(argv)
        assert expected in capsys.readouterr().err

    @pytest.mark.parametrize(
        "argv",
        [
            ["--stage", "1", "--audio-file-id", "af-1"],
            ["--stage", "1", "--limit", "3"],
            ["--stage", "2", "--context-before-seconds", "10", "--context-after-seconds", "5"],
            ["--stage", "3", "--snippet-id", "s-1", "--skip-review"],
            ["--stage", "4", "--snippet-id", "s-1"],
            ["--stage", "5"],
        ],
    )
    def test_accepts_valid_options_per_stage(self, run_stage, argv):
        assert run_stage.parse_args(argv).stage == int(argv[1])


class TestDispatch:
    def test_stage_1(self, run_stage):
        with patch("processing_pipeline.stage_1.initial_disinformation_detection") as flow:
            run_stage.main(["--stage", "1", "--audio-file-id", "af-1", "--env-file", "/nonexistent/.env"])
        flow.assert_called_once_with(audio_file_id="af-1", limit=1)

    def test_stage_2(self, run_stage):
        with patch("processing_pipeline.stage_2.audio_clipping") as flow:
            run_stage.main(["--stage", "2", "--context-before-seconds", "10", "--env-file", "/nonexistent/.env"])
        flow.assert_called_once_with(context_before_seconds=10, context_after_seconds=60, repeat=False)

    def test_stage_3(self, run_stage):
        with patch("processing_pipeline.stage_3.in_depth_analysis", new=AsyncMock()) as flow:
            run_stage.main(["--stage", "3", "--snippet-id", "s-1", "--skip-review", "--env-file", "/nonexistent/.env"])
        flow.assert_awaited_once_with(snippet_ids=["s-1"], skip_review=True, repeat=False)

    def test_stage_4(self, run_stage):
        with patch("processing_pipeline.stage_4.analysis_review", new=AsyncMock()) as flow:
            run_stage.main(["--stage", "4", "--snippet-id", "s-1", "--env-file", "/nonexistent/.env"])
        flow.assert_awaited_once_with(snippet_ids=["s-1"], repeat=False)

    def test_stage_5(self, run_stage):
        with patch("processing_pipeline.stage_5.embedding") as flow:
            run_stage.main(["--stage", "5", "--env-file", "/nonexistent/.env"])
        flow.assert_called_once_with(repeat=False)
