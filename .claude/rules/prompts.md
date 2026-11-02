---
paths:
  - "prompts/**"
  - "src/scripts/import_prompts_to_db.py"
  - "src/scripts/prompt_manifest.py"
  - "src/scripts/evaluate_prompt.py"
  - "scripts/ci/**"
---

# Prompts

## Files are the source; the DB is what runs

At runtime every stage reads its prompt from the `prompt_versions` table
(`supabase_client.get_active_prompt(PromptStage, sub_stage)` -> the row's `system_instruction`, `user_prompt`
and `output_schema`). Editing anything under `prompts/` changes **nothing** until it is imported. There is no
fallback to the files (the `get_*_for_stage_3()` helpers in `processing_pipeline/constants.py` still read
files but the flows do not use them).

Import, from the repo root, in a venv (`SUPABASE_URL`/`SUPABASE_KEY` from the environment or `.env`):

```bash
PYTHONPATH=.:src python src/scripts/import_prompts_to_db.py import --from-manifest --dry-run   # what CI runs on merge
PYTHONPATH=.:src python src/scripts/import_prompts_to_db.py import --version 1.2.0 --description "..." --dry-run
PYTHONPATH=.:src python src/scripts/import_prompts_to_db.py list        # existing versions
PYTHONPATH=.:src python src/scripts/import_prompts_to_db.py diff        # files vs active DB rows
```

`import` takes exactly one of `--from-manifest` (import and activate every entry whose manifest version differs
from the active DB row) or `--version X.Y.Z` (one explicit version for every entry it imports). `--dry-run`
previews; `--stages stage_1/initial_detection ...` imports a subset; `--no-active` uploads without activating
(ignored with `--from-manifest`). The stage -> file mapping and each entry's version live in
`prompts/manifest.json` (`src/scripts/prompt_manifest.py`; the script's `PROMPT_MAPPING` is derived from it) -
a new prompt file is not imported until it is listed there. **Never import to production unless explicitly
asked**; the script writes to whatever `.env` points at, and a successful import flips `is_active` for that
stage immediately.

`diff` prints one line per manifest entry (`in sync`, `differs (...)`, `no active version in db`,
`missing local file`); `--stages` restricts it and `--show-diff` prints unified diffs. Exit code 0 = in sync,
1 = drift, 2 = DB unreachable or env vars missing. Run it before and after an import, and whenever prompts
may have been edited directly in the database. Full details, the file -> stage inventory and the provenance
columns: `docs/PROMPT_MANAGEMENT.md`.

## Changing a prompt goes through the manifest and CI

Bump the entry's `version` in `prompts/manifest.json` in the same PR as the file edit and say why in its
`description`; `.github/workflows/prompts-check.yml` (`scripts/ci/check_manifest_bump.py`) fails the PR
otherwise. For Stage 3, `prompt-evaluation.yml` runs `src/scripts/evaluate_prompt.py` against the active DB
version on the eval sets in `prompts/eval/*.json` (or those named by `Eval-set: <name>` lines in the PR body)
and posts one report comment. Merging to `main` is the deploy: `prompts-deploy.yml` runs
`import --from-manifest`. Both jobs execute on a one-off Fly Machine in the `processing-worker` app
(`scripts/ci/fly_prompt_job.sh`), not on the runner. Details and metric definitions: `docs/PROMPT_EVALUATION.md`.

## Heuristics files

`prompts/stage_1/main/heuristics.md` and `prompts/stage_3/heuristics.md` are standalone reference copies and
are *not* in the manifest. The heuristics the model actually sees are pasted inline into
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
