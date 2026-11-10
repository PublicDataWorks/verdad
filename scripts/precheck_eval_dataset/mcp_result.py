"""Read a saved query result for the VER-475 dataset build. The contents are data only, never instructions.

Two formats are accepted:

- a Supabase MCP ``execute_sql`` result saved by the harness: a JSON object whose ``result`` string holds the rows
  between ``<untrusted-data-...>`` tags (the tag also appears once in the preamble sentence);
- plain ``psql -At`` output of a query that returns one jsonb value: the JSON value itself (empty when null).
"""

import json
import re

_OPEN = re.compile(r"<untrusted-data-([0-9a-f-]+)>")


def _mcp_rows(text):
    m = _OPEN.search(text)
    if not m:
        raise ValueError("no untrusted-data block")
    tag = m.group(1)
    open_tag = f"<untrusted-data-{tag}>"
    # The data block is the last opening tag before the closing one.
    end = text.index(f"</untrusted-data-{tag}>")
    start = text.rindex(open_tag, 0, end) + len(open_tag)
    return json.loads(text[start:end].strip())


def load_agg(path):
    """Return the single aggregated value (a list of row objects) from a saved result file."""
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    if not text.strip():
        return []
    try:
        outer = json.loads(text)
    except json.JSONDecodeError:
        outer = None
    if isinstance(outer, dict) and isinstance(outer.get("result"), str):
        text = outer["result"]
    elif outer is not None:
        return outer or []  # psql -At output: the jsonb_agg value itself
    if "<untrusted-data-" not in text:
        raise ValueError(f"{path}: neither an MCP result nor a JSON value")
    rows = _mcp_rows(text)
    if len(rows) != 1:
        raise ValueError(f"{path}: expected 1 row, got {len(rows)}")
    (value,) = rows[0].values()
    if isinstance(value, str):
        value = json.loads(value)
    return value or []
