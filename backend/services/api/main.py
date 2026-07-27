"""
CEREBRO v2 API gateway.

Replaces v1's Express server. Three structural differences worth naming:

  1. Every response carries `model_version`. A verdict that cannot name the model
     that produced it is not auditable, and an unauditable security tool is a
     liability rather than a product.

  2. Gmail access tokens are never accepted from the client. v1's
     /api/gmail-send-alert took an `accessToken` in the POST body from any
     caller with no session check — effectively an open mail relay. Here tokens
     live server-side, keyed by authenticated session.

  3. Nothing here calls an LLM to make a decision. Routes call feature
     extractors and fitted models; the LLM is invoked only to write prose about
     results that already exist.
"""

from __future__ import annotations

import logging
import os
import time
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from services.api.core.config import settings
from services.api.core.db import db
from services.api.routers import auth as auth_router
from services.api.routers import email as email_router
from services.api.routers import flows as flows_router
from services.api.routers import forecast as forecast_router
from services.api.routers import health as health_router
from services.api.routers import metrics as metrics_router
from services.api.routers import network as network_router
from services.api.routers import news as news_router
from services.api.routers import stream as stream_router

logging.basicConfig(
    level=settings.log_level,
    format='{"ts":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}',
)
log = logging.getLogger("cerebro.api")


async def _seed_demo_user() -> None:
    """
    Create a demo tenant + owner login the first time the DB is empty, so a fresh
    deploy is usable before a registration flow exists. Idempotent: if any user
    already exists, this does nothing and never touches real accounts.
    """
    existing = await db.fetch_unscoped("SELECT 1 FROM cerebro.users LIMIT 1")
    if existing:
        return
    from services.api.core.security import hash_password

    tenant = await db.fetch_unscoped(
        """
        INSERT INTO cerebro.tenants (name, slug) VALUES ('Demo', 'demo')
        ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name
        RETURNING id
        """
    )
    tenant_id = tenant[0]["id"]
    await db.fetch_unscoped(
        """
        INSERT INTO cerebro.users (tenant_id, email, display_name, role, password_hash)
        VALUES ($1, $2, 'Demo Admin', 'owner', $3)
        ON CONFLICT (tenant_id, email) DO NOTHING
        """,
        tenant_id, settings.demo_email, hash_password(settings.demo_password),
    )
    log.info("seeded demo user %s", settings.demo_email)


def _load_models(app: FastAPI) -> None:
    """Load trained model artifacts named in the environment, if they exist."""
    import os

    clf_path = settings.email_classifier_path
    if clf_path and os.path.exists(clf_path):
        try:
            from services.ml.email.classifier import PhishingClassifier
            app.state.models["email_classifier"] = PhishingClassifier.load(clf_path)
            log.info("loaded email_classifier %s",
                     app.state.models["email_classifier"].version)
        except Exception as exc:  # noqa: BLE001
            log.warning("failed to load email classifier from %s: %s", clf_path, exc)

    anomaly_path = settings.anomaly_model_path
    if anomaly_path and os.path.exists(anomaly_path):
        try:
            from services.ml.anomaly.detector import NetworkAnomalyDetector
            app.state.models["anomaly"] = NetworkAnomalyDetector.load(anomaly_path)
            log.info("loaded anomaly detector from %s", anomaly_path)
        except Exception as exc:  # noqa: BLE001
            log.warning("failed to load anomaly model from %s: %s", anomaly_path, exc)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """
    Load models once at startup, not per request.

    v1 constructed a new Gemini client on every single request. Model loading is
    expensive; do it here so the first user request isn't the one that pays.
    """
    log.info("starting CEREBRO API env=%s", settings.environment)
    app.state.started_at = time.time()
    app.state.models = {}

    # Database pool + the LISTEN connection behind the realtime stream. A failure
    # here is logged but does NOT abort startup: email forensics is deterministic
    # and needs no database, so the service still serves /v1/analyze/email and the
    # health probes. Only the metrics/flows/stream routes degrade to 503.
    app.state.db_ok = False
    try:
        await db.connect()
        app.state.db_ok = True
        if settings.auto_apply_schema:
            try:
                await db.apply_schema()
            except Exception as exc:  # noqa: BLE001
                log.warning("auto schema apply failed (%s); apply db/schema_portable.sql manually", exc)
        if settings.seed_demo_user:
            try:
                await _seed_demo_user()
            except Exception as exc:  # noqa: BLE001
                log.warning("demo user seed skipped (%s)", exc)
    except Exception as exc:  # noqa: BLE001
        log.warning("database unavailable at startup (%s); metrics/stream disabled", exc)

    # Trained models load here when their artifacts are present. Absence is not
    # an error — the email module falls back to its transparent heuristic prior,
    # and the network module honestly reports it has no model. Their presence is
    # what flips score_source from 'heuristic' to 'model'.
    _load_models(app)

    from services.ml.providers.llm import default_chain
    app.state.llm = default_chain()
    log.info("llm chain: %s", [p.name for p in app.state.llm.providers])

    yield

    log.info("shutting down")
    if app.state.db_ok:
        await db.close()


app = FastAPI(
    title="CEREBRO API",
    description=(
        "Threat and misinformation intelligence. Every verdict is traceable to "
        "features, a model version, and — where applicable — retrieved evidence."
    ),
    version="2.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    openapi_url="/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_timing_and_request_id(request: Request, call_next):
    """Latency headers on every response — you cannot optimize what you don't measure."""
    start = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - start) * 1000
    response.headers["X-Response-Time-ms"] = f"{elapsed_ms:.1f}"
    response.headers["X-CEREBRO-Version"] = app.version
    if elapsed_ms > 1000:
        log.warning("slow request %s %s took %.0fms",
                    request.method, request.url.path, elapsed_ms)
    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """
    Never leak internals to the client.

    v1's firebase.ts built an error object containing the user's uid, email,
    emailVerified, tenantId and every linked provider email — then both logged
    it AND threw it, so it could surface in the UI. That is a data leak wearing
    an error message's clothes.
    """
    log.exception("unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"error": "internal_error",
                 "message": "An internal error occurred. The incident has been logged."},
    )


app.include_router(health_router.router, tags=["system"])
app.include_router(email_router.router, prefix="/v1", tags=["email"])
app.include_router(news_router.router, prefix="/v1")
app.include_router(network_router.router, prefix="/v1")
app.include_router(auth_router.router, prefix="/v1")
app.include_router(metrics_router.router, prefix="/v1")
app.include_router(flows_router.router, prefix="/v1")
app.include_router(forecast_router.router, prefix="/v1")
app.include_router(stream_router.router, prefix="/v1")


@app.get("/", include_in_schema=False)
async def root() -> dict[str, Any]:
    return {
        "service": "cerebro",
        "version": app.version,
        "docs": "/docs",
        "modules": ["email", "news", "network", "forecast"],
    }
