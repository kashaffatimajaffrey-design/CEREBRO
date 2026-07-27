"""
Named-query registry.

`db/queries.sql` holds the dashboard and metrics queries as plain SQL, one per
`-- name:` marker, so they can be EXPLAIN'd and profiled outside the app. This
module parses that file once at import and exposes each statement by name.

Why load from a file rather than embed SQL in Python string literals:

  - The queries stay reviewable as SQL — a DBA can read `queries.sql` without
    reading Python, and `psql -f` still works for profiling.
  - There is exactly one copy of each statement. v1 had the same "credibility"
    logic pasted into several handlers; they drifted.
  - A test (`tests/test_queries.py`) asserts every name the routers reference
    actually exists, so a typo fails the build rather than a 500 at runtime.

The parser is deliberately tiny and dependency-free: it needs no database, so
it is unit-testable in any environment.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

# db/queries.sql lives at  backend/db/queries.sql.
# This file is at         backend/services/api/core/queries.py  → parents[3] = backend
_QUERIES_PATH = Path(__file__).resolve().parents[3] / "db" / "queries.sql"

_NAME_RE = re.compile(r"^--\s*name:\s*(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*$")


def _parse(text: str) -> dict[str, str]:
    """
    Split a .sql file into {name: statement}.

    A block starts at a `-- name: foo` line and runs until the next one (or EOF).
    Other comment lines inside a block (`-- params:`, `-- Replaces ...`) are kept
    verbatim — they are valid SQL comments and harmless to send to the server,
    and stripping them would lose the parameter documentation.
    """
    blocks: dict[str, str] = {}
    current: str | None = None
    buffer: list[str] = []

    def flush() -> None:
        if current is not None:
            body = "\n".join(buffer).strip()
            if not body:
                raise ValueError(f"query '{current}' is empty")
            blocks[current] = body

    for line in text.splitlines():
        m = _NAME_RE.match(line.strip())
        if m:
            flush()
            name = m.group("name")
            if name in blocks:
                raise ValueError(f"duplicate query name: {name!r}")
            current = name
            buffer = []
        elif current is not None:
            buffer.append(line)

    flush()
    if not blocks:
        raise ValueError(f"no '-- name:' markers found in {_QUERIES_PATH}")
    return blocks


@lru_cache(maxsize=1)
def _registry() -> dict[str, str]:
    return _parse(_QUERIES_PATH.read_text(encoding="utf-8"))


def get_query(name: str) -> str:
    """Return the SQL for a named query, or raise KeyError with the known names."""
    reg = _registry()
    try:
        return reg[name]
    except KeyError as exc:
        raise KeyError(
            f"unknown query {name!r}. Known queries: {', '.join(sorted(reg))}"
        ) from exc


def query_names() -> list[str]:
    return sorted(_registry())
