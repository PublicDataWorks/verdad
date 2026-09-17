import json

from src.scripts.import_prompts_to_db import compare_prompt_entry, load_local_prompt

SCHEMA = {"type": "object", "properties": {"flagged": {"type": "boolean"}}}
LOCAL = {
    "system_instruction": "You are a detector.",
    "user_prompt": "Analyze this: {transcription}",
    "output_schema": SCHEMA,
}


def db_row(**overrides):
    row = {"id": "row-1", "stage": "stage_1", "sub_stage": "initial_detection", "version": "1.0.0", **LOCAL}
    row.update(overrides)
    return row


def test_identical_content_is_in_sync():
    assert compare_prompt_entry(LOCAL, db_row()) == ("in sync", [])


def test_output_schema_is_compared_as_parsed_json():
    reordered = json.dumps({"properties": {"flagged": {"type": "boolean"}}, "type": "object"}, indent=4)
    assert compare_prompt_entry(LOCAL, db_row(output_schema=reordered)) == ("in sync", [])


def test_null_and_empty_text_fields_are_equal():
    local = {"user_prompt": "hello", "system_instruction": ""}
    row = db_row(system_instruction=None, user_prompt="hello", output_schema=None)
    assert compare_prompt_entry(local, row) == ("in sync", [])


def test_differing_fields_are_named_in_field_order():
    row = db_row(system_instruction="Old instruction.", output_schema={"type": "string"})
    assert compare_prompt_entry(LOCAL, row) == ("differs", ["system_instruction", "output_schema"])


def test_extra_field_in_db_counts_as_drift():
    local = {"system_instruction": "Only instruction."}
    row = db_row(system_instruction="Only instruction.", user_prompt="Unexpected", output_schema=None)
    assert compare_prompt_entry(local, row) == ("differs", ["user_prompt"])


def test_no_active_version_in_db():
    assert compare_prompt_entry(LOCAL, None) == ("no active version in db", [])


def test_missing_local_file_takes_precedence():
    assert compare_prompt_entry(None, None) == ("missing local file", [])
    assert compare_prompt_entry(None, db_row()) == ("missing local file", [])


def test_load_local_prompt_reads_text_and_json(tmp_path):
    (tmp_path / "prompt.md").write_text("Hello {kb_context}", encoding="utf-8")
    (tmp_path / "schema.json").write_text(json.dumps(SCHEMA), encoding="utf-8")
    files = {"user_prompt": str(tmp_path / "prompt.md"), "output_schema": str(tmp_path / "schema.json")}
    assert load_local_prompt(files) == {"user_prompt": "Hello {kb_context}", "output_schema": SCHEMA}


def test_load_local_prompt_returns_none_when_a_file_is_missing(tmp_path):
    (tmp_path / "prompt.md").write_text("Hello", encoding="utf-8")
    files = {"user_prompt": str(tmp_path / "prompt.md"), "output_schema": str(tmp_path / "missing.json")}
    assert load_local_prompt(files) is None
