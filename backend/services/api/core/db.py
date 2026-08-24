"""
Database access layer.

Two responsibilities live here, and both are security-critical:

  1. **Tenant-scoped connections.** Every query the API runs must see only one
     tenant's rows. The schema enforces this with row-level security keyed off
     `current_setting('app.tenant_id')`; this module is what sets that variable,
     per request, inside a transaction so it cannot leak to the next borrower of
     a pooled connection. Application code never filters by tenant by hand — if
     it forgets, RLS returns zero rows, which is the safe direction to fail.

  2. **The realtime bridge.** One long-lived connection holds `LISTEN
     cerebro_events`. When a detection commits, Postgres fires the payload to
     that connection with no polling; we fan it out to every subscribed
     WebSocket. This is the mechanism behind the "event-driven dashboard" claim.

Why asyncpg directly rather than the SQLAlchemy ORM:
  - `db/queries.sql` is written with native `$1,$2` placeholders and is meant to
    be run verbatim; asyncpg speaks that dialect, SQLAlchemy would re-parse it.
  - `set_config()` for RLS and `LISTEN/NOTIFY` are both first-class in asyncpg
    and awkward through the ORM. There is no object-graph to map here — the
    queries return analytics rows, not entities — so the ORM would be overhead
    with no payoff.
"""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

from services.api.core.config import settings

log = logging.getLogger(__name__)

# The event channel the schema's notify_detection()/notify_incident() publish to.
EVENT_CHANNEL = "cerebro_events"


def _asyncpg_dsn(url: str) -> str:
    """
    Normalize a SQLAlchemy-style URL to what asyncpg accepts.

    Config and deploy docs use `postgresql+asyncpg://...` (the SQLAlchemy form);
    asyncpg itself wants a bare `postgresql://...`. Strip the driver suffix so a
    single DATABASE_URL works for both worlds.
    """
    return url.replace("postgresql+asyncpg://", "postgresql://", 1).replace(
        "postgres+asyncpg://", "postgresql://", 1
    )


class Database:
    """Owns the connection pool and the realtime listener for the process."""

    def __init__(self, dsn: str | None = None) -> None:
        self._dsn = _asyncpg_dsn(dsn or settings.database_url)
        self._pool: Any = None
        self._listen_conn: Any = None
        # WebSocket fan-out. Each subscriber is an asyncio.Queue we push onto.
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()

    # -- lifecycle ----------------------------------------------------------

    async def connect(self) -> None:
        import asyncpg

        self._pool = await asyncpg.create_pool(
            self._dsn,
            min_size=1,
            max_size=10,
            # search_path so unqualified names resolve to the cerebro schema;
            # the queries qualify explicitly too, so this is belt-and-braces.
            server_settings={"search_path": "cerebro,public"},
        )
        log.info("database pool created")
        # The realtime listener is best-effort: if LISTEN can't be established
        # (e.g. a pooler like PgBouncer in transaction mode forbids it), metrics
        # and flows still work — only the live WebSocket push degrades to the
        # 60-second fallback poll the dashboard already implements.
        try:
            await self._start_listener()
        except Exception as exc:  # noqa: BLE001
            log.warning("realtime listener unavailable (%s); stream falls back to poll", exc)

    async def close(self) -> None:
        if self._listen_conn is not None:
            try:
                await self._listen_conn.close()
            except Exception:  # noqa: BLE001 - shutdown best-effort
                pass
        if self._pool is not None:
            await self._pool.close()
        log.info("database pool closed")

    @property
    def is_connected(self) -> bool:
        return self._pool is not None

    # -- tenant-scoped queries ---------------------------------------------

    @asynccontextmanager
    async def tenant_connection(self, tenant_id: str) -> AsyncIterator[Any]:
        """
        Yield a connection with `app.tenant_id` set for the enclosed transaction.

        The `is_local=true` argument to set_config scopes the setting to this
        transaction only, so RLS is active for these queries and automatically
        cleared when the transaction ends — even if the connection is handed to
        another request next. Forgetting this is how multi-tenant systems leak.
        """
        if self._pool is None:
            raise RuntimeError("database pool is not initialized")
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "SELECT set_config('app.tenant_id', $1, true)", str(tenant_id)
                )
                yield conn

    async def fetch(self, tenant_id: str, sql: str, *args: Any) -> list[dict[str, Any]]:
        async with self.tenant_connection(tenant_id) as conn:
            rows = await conn.fetch(sql, *args)
            return [dict(r) for r in rows]

    async def fetchrow(
        self, tenant_id: str, sql: str, *args: Any
    ) -> dict[str, Any] | None:
        async with self.tenant_connection(tenant_id) as conn:
            row = await conn.fetchrow(sql, *args)
            return dict(row) if row is not None else None

    async def execute(self, tenant_id: str, sql: str, *args: Any) -> str:
        async with self.tenant_connection(tenant_id) as conn:
            return await conn.execute(sql, *args)

    async def fetch_unscoped(self, sql: str, *args: Any) -> list[dict[str, Any]]:
        """
        For genuinely tenant-independent reads only (e.g. the model registry).
        Never use this for tenant data — it bypasses the RLS scoping above.
        """
        if self._pool is None:
            raise RuntimeError("database pool is not initialized")
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, *args)
            return [dict(r) for r in rows]

    async def apply_schema(self) -> None:
        """
        Apply db/schema_portable.sql. Idempotent (everything is CREATE ... IF NOT
        EXISTS), so safe to run on every boot. Used by one-click hosts where a
        manual psql step is inconvenient; gated behind AUTO_APPLY_SCHEMA.

        asyncpg runs a multi-statement, dollar-quoted script via the simple query
        protocol when there are no parameters, so the functions, DO blocks and
        triggers in the schema apply cleanly.
        """
        if self._pool is None:
            raise RuntimeError("database pool is not initialized")
        schema_path = Path(__file__).resolve().parents[3] / "db" / "schema_portable.sql"
        sql = schema_path.read_text(encoding="utf-8")
        async with self._pool.acquire() as conn:
            await conn.execute(sql)
        log.info("applied schema from %s", schema_path)

    async def ping(self) -> bool:
        if self._pool is None:
            return False
        try:
            async with self._pool.acquire() as conn:
                return await conn.fetchval("SELECT 1") == 1
        except Exception as exc:  # noqa: BLE001
            log.warning("db ping failed: %s", exc)
            return False

    # -- realtime fan-out ---------------------------------------------------

    async def _start_listener(self) -> None:
        """Hold one connection open on LISTEN and re-broadcast every payload."""
        import asyncpg

        self._listen_conn = await asyncpg.connect(self._dsn)
        await self._listen_conn.add_listener(EVENT_CHANNEL, self._on_notify)
        log.info("listening on channel %r", EVENT_CHANNEL)

    def _on_notify(self, _conn: Any, _pid: int, _channel: str, payload: str) -> None:
        try:
            event = json.loads(payload)
        except (json.JSONDecodeError, TypeError):
            log.warning("dropping malformed notify payload")
            return
        # Push to every subscriber. Queues are bounded; a slow client drops
        # events rather than back-pressuring the shared listener connection.
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                log.debug("subscriber queue full; dropping event")

    @asynccontextmanager
    async def subscribe(self) -> AsyncIterator["asyncio.Queue[dict[str, Any]]"]:
        """Register a fan-out queue for the lifetime of a WebSocket."""
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=100)
        self._subscribers.add(queue)
        try:
            yield queue
        finally:
            self._subscribers.discard(queue)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)


# Process-wide singleton, initialized in the FastAPI lifespan.
db = Database()


async def emit_detection(
    tenant_id: str,
    module: str,
    threat_type: str,
    risk_score: float,
    *,
    ref_id: str | None = None,
    summary: str | None = None,
) -> str | None:
    """
    Insert a detection. The AFTER INSERT trigger fires pg_notify, which reaches
    the listener above and every subscribed WebSocket — no application-level
    pub/sub needed. Returns the new detection id.
    """
    row = await db.fetchrow(
        tenant_id,
        """
        INSERT INTO cerebro.detections (tenant_id, module, threat_type, risk_score, ref_id, summary)
        VALUES ($1, $2, $3, $4, $5, $6)
        RETURNING id
        """,
        tenant_id, module, threat_type, risk_score, ref_id, summary,
    )
    return str(row["id"]) if row else None
