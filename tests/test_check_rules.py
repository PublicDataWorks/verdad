import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_rules.py"


@pytest.fixture(scope="module")
def check_rules():
    spec = importlib.util.spec_from_file_location("check_rules", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestGlobMatching:
    @pytest.mark.parametrize(
        "path",
        [
            "src/processing_pipeline/stage_1/flows.py",
            "tests/processing_pipeline/test_stage_1.py",
        ],
    )
    def test_double_star_suffix_matches_any_depth(self, check_rules, path):
        prefix = path.split("/")[0]
        assert check_rules.matches(f"{prefix}/**", [path])

    def test_double_star_slash_matches_zero_directories(self, check_rules):
        # `**/` must also match a file at the repo root; fnmatch's `*/` required a directory.
        assert check_rules.matches("**/__tests__/**", ["__tests__/x.py"])
        assert check_rules.matches("src/**/*.py", ["src/utils.py"])

    def test_double_star_slash_matches_nested_directories(self, check_rules):
        assert check_rules.matches("**/__tests__/**", ["src/apis/__tests__/x.test.ts"])
        assert check_rules.matches("src/**/*.py", ["src/processing_pipeline/stage_1/tasks.py"])

    def test_double_star_slash_only_matches_at_a_path_boundary(self, check_rules):
        assert not check_rules.matches("**/__tests__/**", ["src/foo__tests__/bar.ts"])

    def test_single_star_stays_within_one_segment(self, check_rules):
        assert check_rules.matches("src/*.py", ["src/utils.py"])
        assert not check_rules.matches("src/*.py", ["src/processing_pipeline/main.py"])

    def test_brace_groups_expand(self, check_rules):
        assert check_rules.matches("src/**/*.{py,pyi}", ["src/recording.py"])
        assert not check_rules.matches("src/**/*.{py,pyi}", ["src/notes.md"])

    def test_literal_path_matches_itself_only(self, check_rules):
        assert check_rules.matches("src/recording.py", ["src/recording.py"])
        assert not check_rules.matches("src/recording.py", ["src/generic_recording.py"])


class TestParsePaths:
    def test_reports_missing_frontmatter(self, check_rules, tmp_path):
        rule = tmp_path / "no_frontmatter.md"
        rule.write_text("# Just a heading\n")
        globs, errors = check_rules.parse_paths(rule)
        assert globs == []
        assert "missing YAML frontmatter" in errors[0]

    def test_reports_frontmatter_without_paths(self, check_rules, tmp_path):
        rule = tmp_path / "unscoped.md"
        rule.write_text("---\ndescription: unscoped\n---\n\nBody\n")
        globs, errors = check_rules.parse_paths(rule)
        assert globs == []
        assert "no 'paths:' globs" in errors[0]

    def test_parses_quoted_globs(self, check_rules, tmp_path):
        rule = tmp_path / "scoped.md"
        rule.write_text('---\npaths:\n  - "src/**"\n  - \'tests/**\'\n---\n\nBody\n')
        globs, errors = check_rules.parse_paths(rule)
        assert globs == ["src/**", "tests/**"]
        assert errors == []
