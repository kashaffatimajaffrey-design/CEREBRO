"""
Pre-flight check. Runs before uvicorn binds a port.

The principle: a service that cannot work correctly should refuse to accept
traffic, loudly, at deploy time — not fail on a user's first request with a 500.
v1 read `process.env.GEMINI_API_KEY` inside a per-request helper, so a
misconfigured deploy looked healthy right up until someone used it.

Exit codes:
    0  ready
    1  fatal misconfiguration — deployment should fail
"""

from __future__ import annotations

import os
import sys


GREEN, RED, YELLOW, RESET = "\033[32m", "\033[31m", "\033[33m", "\033[0m"

errors: list[str] = []
warnings: list[str] = []


def check(label: str, ok: bool, detail: str = "", fatal: bool = True) -> None:
    if ok:
        print(f"  {GREEN}PASS{RESET}  {label}")
    elif fatal:
        print(f"  {RED}FAIL{RESET}  {label}  {detail}")
        errors.append(f"{label}: {detail}")
    else:
        print(f"  {YELLOW}WARN{RESET}  {label}  {detail}")
        warnings.append(f"{label}: {detail}")


def main() -> int:
    env = os.getenv("ENVIRONMENT", "development")
    is_prod = env.lower() in {"production", "prod"}
    print(f"\nCEREBRO startup check  (environment={env})\n" + "-" * 52)

    # --- secrets -----------------------------------------------------------
    secret = os.getenv("SECRET_KEY", "")
    check("SECRET_KEY set and >= 32 chars", len(secret) >= 32,
          f"got {len(secret)} chars — generate with "
          "python -c \"import secrets;print(secrets.token_urlsafe(48))\"",
          fatal=is_prod)

    token_key = os.getenv("TOKEN_ENCRYPTION_KEY", "")
    check("TOKEN_ENCRYPTION_KEY set", bool(token_key),
          "required to store OAuth tokens encrypted at rest", fatal=is_prod)

    check("SECRET_KEY != TOKEN_ENCRYPTION_KEY", secret != token_key or not secret,
          "reusing one key for signing and encryption is a cryptographic mistake",
          fatal=is_prod)

    # --- database ----------------------------------------------------------
    db_url = os.getenv("DATABASE_URL", "")
    check("DATABASE_URL set", bool(db_url), "no database configured")
    check("DATABASE_URL is not the dev default",
          "cerebro_dev_pw" not in db_url and "change_me" not in db_url,
          "still using the development password", fatal=is_prod)

    # --- CORS --------------------------------------------------------------
    cors = os.getenv("CORS_ORIGINS", "")
    check("CORS_ORIGINS is not a wildcard", "*" not in cors,
          "'*' with credentials allows any site to call the API", fatal=is_prod)
    check("CORS_ORIGINS configured", bool(cors),
          "frontend will be blocked by the browser", fatal=False)

    # --- model providers ---------------------------------------------------
    # Deliberately non-fatal: detection does not depend on an LLM. Only the
    # prose explanations degrade, and there is always the template fallback.
    providers = {
        "groq": os.getenv("GROQ_API_KEY"),
        "cerebras": os.getenv("CEREBRAS_API_KEY"),
        "gemini": os.getenv("GEMINI_API_KEY"),
        "openai": os.getenv("OPENAI_API_KEY"),
        "ollama": os.getenv("OLLAMA_BASE_URL"),
    }
    configured = [name for name, value in providers.items() if value]
    check(f"LLM provider configured ({', '.join(configured) or 'none'})",
          bool(configured),
          "explanations will use the deterministic template fallback; "
          "detection and scoring are unaffected",
          fatal=False)

    # --- python deps -------------------------------------------------------
    for module, fatal in [("fastapi", True), ("sqlalchemy", True),
                          ("numpy", True), ("sklearn", True),
                          ("transformers", False), ("torch", False)]:
        try:
            __import__(module)
            check(f"import {module}", True)
        except ImportError:
            check(f"import {module}", False,
                  "not installed" + ("" if fatal else
                                     " — RoBERTa/NLI paths will fall back"),
                  fatal=fatal)

    # --- summary -----------------------------------------------------------
    print("-" * 52)
    if errors:
        print(f"{RED}{len(errors)} fatal problem(s). Refusing to start.{RESET}")
        for e in errors:
            print(f"    - {e}")
        return 1

    if warnings:
        print(f"{YELLOW}{len(warnings)} warning(s), starting anyway:{RESET}")
        for w in warnings:
            print(f"    - {w}")

    print(f"{GREEN}All checks passed. Starting CEREBRO.{RESET}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
