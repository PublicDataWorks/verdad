# Pre-check eval dataset build (VER-475)

These files rebuild `precheck_eval.jsonl`, the eval set that the harness in `src/scripts/precheck_eval/` reads. The
full guide is in `docs/PRECHECK_EVALUATION.md`, under "Rebuilding the eval set".

| File | What it does |
|---|---|
| `sql/population.sql` | Lists every clip in the population, with the Stage 3 score and the Stage 4 backup in one value. |
| `sql/details.sql` | Gets the Stage 1 fields, the transcript excerpt for the clip window and station metadata for one page. The psql variable `:'prefixes'` sets the page. |
| `build_dataset.py` | `render-sql`, `sample` and `build`. It reads the saved results and never connects to anything. |
| `mcp_result.py` | Reads a saved Supabase MCP result or plain `psql -At` output. |
| `check_leakage.py` | Checks for duplicate ids and null labels, and checks that no Stage 3 output appears in `input`. |
| `ids.json` | Lists the 2,255 published clips: snippet_id, split, stratum, weight and stage3_overall. It holds no content. |

All SQL is `SELECT` only. The built JSONL holds transcripts, so keep it and the raw query results out of the repo.
