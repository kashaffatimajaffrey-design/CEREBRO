"""
Named-query registry tests.

These need no database — they check that db/queries.sql parses, that every
statement the routers reference by name exists, and that the parser rejects a
malformed file. A typo in a query name should fail here, at build time, not as a
500 in front of a user.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.api.core import queries  # noqa: E402
from services.api.core.queries import _parse, get_query, query_names  # noqa: E402

# Every query name the API routers load. If a router asks for a name that
# queries.sql doesn't define, this list catches it before runtime.
REFERENCED_BY_ROUTERS = [
    "summary",
    "summary_delta",
    "threat_volume",
    "detection_rates",
    "recent_detections",
    "top_threat_domains",
    "auth_failure_breakdown",
    "open_incidents",
    "model_versions_active",
    "forecast_series",
]


def test_queries_file_parses():
    names = query_names()
    assert names, "no queries parsed from db/queries.sql"
    # Names are unique and sorted.
    assert names == sorted(set(names))


def test_every_router_query_exists():
    known = set(query_names())
    missing = [n for n in REFERENCED_BY_ROUTERS if n not in known]
    assert not missing, f"queries.sql is missing statements used by routers: {missing}"


def test_get_query_returns_sql():
    sql = get_query("summary")
    assert "FROM cerebro.detections" in sql
    assert "$1" in sql  # tenant_id is always the first positional parameter


def test_unknown_query_raises_with_hint():
    try:
        get_query("does_not_exist")
    except KeyError as exc:
        # The error should list the known names so a typo is easy to fix.
        assert "summary" in str(exc)
    else:
        raise AssertionError("expected KeyError for an unknown query name")


def test_parser_splits_named_blocks():
    text = (
        "-- name: alpha\n"
        "SELECT 1;\n"
        "-- name: beta\n"
        "-- params: $1 tenant_id\n"
        "SELECT 2 FROM t WHERE tenant_id = $1;\n"
    )
    parsed = _parse(text)
    assert set(parsed) == {"alpha", "beta"}
    assert parsed["alpha"] == "SELECT 1;"
    # Inline comment lines inside a block are preserved (valid SQL, harmless).
    assert "$1" in parsed["beta"]


def test_parser_rejects_duplicate_names():
    try:
        _parse("-- name: dup\nSELECT 1;\n-- name: dup\nSELECT 2;\n")
    except ValueError as exc:
        assert "duplicate" in str(exc).lower()
    else:
        raise AssertionError("expected ValueError on duplicate query name")


def test_parser_rejects_empty_query():
    try:
        _parse("-- name: empty\n\n-- name: real\nSELECT 1;\n")
    except ValueError as exc:
        assert "empty" in str(exc).lower()
    else:
        raise AssertionError("expected ValueError on an empty query body")


if __name__ == "__main__":
    import traceback

    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
            passed += 1
        except Exception:
            print(f"  FAIL  {t.__name__}")
            traceback.print_exc()
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
