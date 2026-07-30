"""
Configuration. Single source of truth, validated at import time.

v1 read process.env.GEMINI_API_KEY inside a helper called on every request, so a
misconfiguration surfaced as a runtime 500 in front of a user. Fail at startup
instead: a service that cannot work should not accept traffic.
"""

from __future__ import annotations

import os
from functools import lru_cache


def _env_list(key: str, default: str) -> list[str]:
    return [item.strip() for item in os.getenv(key, default).split(",") if item.strip()]


class Settings:
    """Plain class rather than pydantic-settings to keep dependencies minimal."""

    def __init__(self) -> None:
        self.environment: str = os.getenv("ENVIRONMENT", "development")
        self.log_level: str = os.getenv("LOG_LEVEL", "INFO").upper()

        self.database_url: str = os.getenv(
            "DATABASE_URL",
            "postgresql+asyncpg://cerebro:cerebro_dev_pw@localhost:5432/cerebro",
        )
        self.redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")

        # Local-first by default. No API key required to run the platform.
        self.llm_provider: str = os.getenv("LLM_PROVIDER", "ollama")
        self.ollama_base_url: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        self.ollama_model: str = os.getenv("OLLAMA_MODEL", "qwen2.5:7b-instruct")

        self.embedding_model: str = os.getenv("EMBEDDING_MODEL", "BAAI/bge-base-en-v1.5")
        self.reranker_model: str = os.getenv("RERANKER_MODEL",
                                             "cross-encoder/ms-marco-MiniLM-L-6-v2")
        self.nli_model: str = os.getenv("NLI_MODEL", "roberta-large-mnli")
        self.embedding_dim: int = int(os.getenv("EMBEDDING_DIM", "768"))

        self.cors_origins: list[str] = _env_list(
            "CORS_ORIGINS", "http://localhost:3000,http://localhost:5173")
        # Also allow origins by regex — Vercel assigns per-project/preview
        # subdomains (cerebro-<suffix>.vercel.app), so matching the pattern means
        # a URL change doesn't break auth. Scoped to this project's Vercel URLs.
        self.cors_origin_regex: str = os.getenv(
            "CORS_ORIGIN_REGEX", r"https://cerebro-[a-z0-9-]+\.vercel\.app")

        self.secret_key: str = os.getenv("SECRET_KEY", "")
        self.access_token_ttl_minutes: int = int(os.getenv("ACCESS_TOKEN_TTL_MINUTES", "60"))

        # Session cookie policy. For a SPLIT deploy — frontend on Netlify/Vercel,
        # API on Railway (different sites) — the cookie must be SameSite=None so
        # the browser sends it cross-site, which in turn requires Secure=True.
        # Set SESSION_COOKIE_SAMESITE=none in that case. For same-origin (dev
        # proxy, or one domain) leave it 'lax'.
        self.session_cookie_samesite: str = os.getenv("SESSION_COOKIE_SAMESITE", "lax").lower()

        # Google OAuth — for the server-side Gmail token exchange. The client id
        # is a public identifier; the secret must never reach the browser, which
        # is the whole reason the exchange happens on the server.
        self.google_client_id: str = os.getenv("GOOGLE_CLIENT_ID", "")
        self.google_client_secret: str = os.getenv("GOOGLE_CLIENT_SECRET", "")
        self.google_token_url: str = os.getenv(
            "GOOGLE_TOKEN_URL", "https://oauth2.googleapis.com/token")
        self.token_encryption_key: str = os.getenv("TOKEN_ENCRYPTION_KEY", "")

        self.rate_limit_per_minute: int = int(os.getenv("RATE_LIMIT_PER_MINUTE", "60"))
        self.max_upload_bytes: int = int(os.getenv("MAX_UPLOAD_BYTES", str(10 * 1024 * 1024)))

        # Trained model artifacts. When set and present, these flip the relevant
        # module from its heuristic/unfitted state to a real model at startup.
        self.email_classifier_path: str = os.getenv("EMAIL_CLASSIFIER_PATH", "")
        self.anomaly_model_path: str = os.getenv("ANOMALY_MODEL_PATH", "")

        # Apply db/schema_portable.sql on startup. Handy for one-click hosts
        # (Render blueprint) where running psql by hand is awkward. The schema is
        # fully idempotent (CREATE ... IF NOT EXISTS), so re-running is safe.
        self.auto_apply_schema: bool = os.getenv("AUTO_APPLY_SCHEMA", "false").lower() in {
            "1", "true", "yes", "on"
        }

        # Seed a demo tenant + login on first boot IF the users table is empty.
        # For getting a fresh deploy usable without a registration flow. Never
        # overwrites existing users. Change the password before anything public.
        self.seed_demo_user: bool = os.getenv("SEED_DEMO_USER", "false").lower() in {
            "1", "true", "yes", "on"
        }
        self.demo_email: str = os.getenv("DEMO_EMAIL", "demo@cerebro.app")
        self.demo_password: str = os.getenv("DEMO_PASSWORD", "cerebro-demo-2026")

        self._validate()

    @property
    def is_production(self) -> bool:
        return self.environment.lower() in {"production", "prod"}

    def _validate(self) -> None:
        if self.is_production:
            problems = []
            if not self.secret_key or len(self.secret_key) < 32:
                problems.append("SECRET_KEY must be set and at least 32 chars")
            if "cerebro_dev_pw" in self.database_url:
                problems.append("DATABASE_URL still uses the development password")
            if "*" in self.cors_origins:
                problems.append("CORS_ORIGINS must not be '*' in production")
            if problems:
                raise RuntimeError(
                    "Refusing to start in production with: " + "; ".join(problems)
                )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
