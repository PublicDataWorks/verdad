---
paths:
  - "prompts/**"
  - "src/scripts/import_prompts_to_db.py"
---

# Prompts

## Files are the source; the DB is what runs

At runtime every stage reads its prompt from the `prompt_versions` table
(`supabase_client.get_active_prompt(PromptStage, sub_stage)` -> the row's `system_instruction`, `user_prompt`
and `output_schema`). Editing anything under `prompts/` changes **nothing** until it is imported. There is no
fallback to the files (the `get_*_for_stage_3()` helpers in `processing_pipeline/constants.py` still read
files but the flows do not use them).

Import, from the repo root, in a venv:

```bash
PYTHONPATH=.:src python src/scripts/import_prompts_to_db.py import --version 1.2.0 --description "..." --dry-run
PYTHONPATH=.:src python src/scripts/import_prompts_to_db.py list        # existing versions
```

`--dry-run` previews; `--stages stage_1/initial_detection ...` imports a subset; `--no-active` uploads without
activating. The stage -> file mapping is `PROMPT_MAPPING` at the top of the script - a new prompt file is not
imported until it is listed there. **Never import to production unless explicitly asked**; the script writes
to whatever `.env` points at, and a successful import flips `is_active` for that stage immediately.

## Heuristics files

`prompts/stage_1/main/heuristics.md` and `prompts/stage_3/heuristics.md` are standalone reference copies and
are *not* in `PROMPT_MAPPING`. The heuristics the model actually sees are pasted inline into
`prompts/stage_1/main/detection_user_prompt.md` and `prompts/stage_3/analysis_prompt.md`, so a category edit
has to land in both the reference file and the user prompt, for both stages.

Format (21 numbered categories, identical numbering in both stages): `### **N. Title**`, then
**Description**, **Common Narratives**, **Cultural/Regional Variations** with separate
*Spanish-Speaking Communities* and *Arabic-Speaking Communities* bullet lists (each with the in-language
phrase in bold plus an English gloss in parentheses), **Potential Legitimate Discussions**, and **Examples**
given as `- _Spanish_: "..."` / `- _Arabic_: "..."` pairs; some categories add
**Examples of What IS / is NOT Disinformation**. Every example must exist in both languages - the whole point
is that detection is bilingual - and the "legitimate discussions" section is what keeps the model from
flagging ordinary debate.

Use the `.claude/skills/verdad-heuristics-updater` skill for any category or heuristics change: it knows the
ordering, the two-stage duplication and the import step.
