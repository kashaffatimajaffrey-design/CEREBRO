# Deploying CEREBRO

Three paths, cheapest first. Pick one for the backend and one for the frontend.
Everything here is copy-paste; the only manual steps are logging into your own
accounts (which is the one thing that can't be automated for you).

The stack: **backend** = FastAPI + Postgres/pgvector (Docker); **frontend** =
static Vite SPA. They are deployed separately and talk over HTTPS + a WebSocket.

---

## Fastest FREE path (recommended): Render blueprint + Vercel

Zero secret-typing on the backend — [`render.yaml`](../render.yaml) provisions the
API + a free Postgres, generates the secrets, wires `DATABASE_URL`, and applies the
schema on first boot (`AUTO_APPLY_SCHEMA=true`). Uses the slim image
([`backend/Dockerfile.render`](../backend/Dockerfile.render)) so it fits the free
512 MB tier.

**Backend (Render) — ~4 clicks:**
1. Push this repo to GitHub.
2. [render.com](https://render.com) → **New → Blueprint** → connect the repo → **Apply**.
   Render reads `render.yaml`, provisions Postgres + the API, and generates
   `SECRET_KEY` / `TOKEN_ENCRYPTION_KEY`.
3. When it's live, copy the API URL (e.g. `https://cerebro-api.onrender.com`).

**Frontend (Vercel) — ~3 clicks:**
4. [vercel.com](https://vercel.com) → **Add New → Project** → import the repo →
   set **Root Directory = `frontend`** and env `VITE_API_BASE=<the Render URL>` → Deploy.

**Wire the two together (1 field each):**
5. Render → `cerebro-api` → Environment → set `CORS_ORIGINS=https://<your-vercel-url>`.
6. If your API is NOT on `*.onrender.com`/`*.railway.app`, edit `connect-src` in
   [`frontend/vercel.json`](../frontend/vercel.json) to your API's `https://` +
   `wss://` origin and redeploy. (For `*.onrender.com`, add
   `https://*.onrender.com wss://*.onrender.com` to `connect-src`.)

Free-tier caveats (Render's, not ours): the web service sleeps after ~15 min idle
(first request cold-starts ~30 s) and the free Postgres expires after 30 days.
Fine for a demo/FYP. **Note:** the slim image omits torch, so RoBERTa-grade NLI
and TFT are off here; forensics, the trained classifier, DB/metrics/auth, and
RAG-with-fallback all work. For full ML use Hugging Face Spaces (16 GB free) or a
paid instance with `requirements.txt`.

---

---

## Before you start — generate secrets

```bash
python -c "import secrets; print('SECRET_KEY=' + secrets.token_urlsafe(48))"
python -c "import secrets; print('TOKEN_ENCRYPTION_KEY=' + secrets.token_urlsafe(32))"
```

Keep these; you'll paste them into the backend host's env. `startup_check.py`
**refuses to boot** on a weak `SECRET_KEY`, a dev DB password, or `CORS_ORIGINS=*`
in production — so set them properly or the container won't start (by design).

---

## Backend

### Option A — Railway (recommended, ~$5/mo)

1. Push this repo to GitHub, then on [railway.app](https://railway.app):
   **New Project → Deploy from GitHub repo**. Railway reads
   [`infra/railway.json`](railway.json) and builds `backend/Dockerfile`.
2. **Add Postgres**: *New → Database → PostgreSQL*. Then enable pgvector:
   open its *Query* tab and run `CREATE EXTENSION IF NOT EXISTS vector;`
3. **Apply the schema** — from your laptop, against the Railway DB URL:
   ```bash
   psql "<RAILWAY_DATABASE_URL>" -f backend/db/schema_portable.sql
   ```
4. **Set variables** on the API service (Variables tab):
   ```
   ENVIRONMENT=production
   SECRET_KEY=<generated above>
   TOKEN_ENCRYPTION_KEY=<generated above>
   DATABASE_URL=postgresql+asyncpg://<user>:<pass>@<host>:<port>/<db>   # from the Postgres plugin
   CORS_ORIGINS=https://<your-frontend-domain>
   SESSION_COOKIE_SAMESITE=none          # frontend is a different site → required
   LLM_PROVIDER=groq                     # optional; GROQ_API_KEY for explanations
   GROQ_API_KEY=<optional>
   EMAIL_CLASSIFIER_PATH=                 # optional; see note below
   ```
5. Deploy. Health check is `/health`; the interactive docs are at `/docs`.

> **RoBERTa note:** the full `requirements.txt` pulls torch + transformers (~2.5 GB
> RAM at load). If the free/hobby instance OOMs, either bump the instance, or run
> the heavy ML service on your own machine behind a Cloudflare Tunnel and keep
> only the API + forensics on Railway. Detection (email forensics) needs neither.

### Option B — Self-host (Raspberry Pi 4/5 8 GB, or any VPS) — $0 extra

The whole stack is already a compose file — no third-party account at all.

```bash
git clone <your-repo> && cd cerebro
make setup                      # writes .env, prints secrets — paste them into backend/.env
docker compose up -d            # db (pgvector) + redis + minio + api
# add local explanations too (needs ~5 GB RAM, skip on a Pi):
# docker compose --profile llm up -d
```

Then put **Caddy** or **Cloudflare Tunnel** in front for HTTPS + a public
hostname. On a Pi, `docker compose` runs the ARM images fine; the only thing to
drop is Ollama (use Groq for explanations, or the template fallback).

---

## Frontend (static SPA)

Set **one** build-time variable — the backend's public URL — then deploy. It is
baked into the bundle at build time, so rebuild if the API URL changes.

```
VITE_API_BASE=https://<your-backend-domain>
```

### Netlify
Uses [`infra/netlify.toml`](netlify.toml) (base `frontend/`, publish `dist`,
CSP + SPA redirects already set).
```bash
# UI: New site from Git → it auto-detects netlify.toml.
# CLI: npm i -g netlify-cli && netlify deploy --build --prod
```

### Vercel
Uses [`frontend/vercel.json`](../frontend/vercel.json) (SPA rewrites + the same
security headers). In the Vercel project settings set **Root Directory =
`frontend`**, add `VITE_API_BASE`, deploy.
```bash
# CLI: npm i -g vercel && cd frontend && vercel --prod
```

---

## The two cross-origin gotchas (read this or auth silently fails)

Because the frontend and API are on **different domains**, two things must line up:

1. **Session cookie must be cross-site.** Set `SESSION_COOKIE_SAMESITE=none` on
   the backend (done above). The code then forces `Secure`, so it only works over
   HTTPS — which both hosts give you. Without this the login cookie is dropped and
   every authenticated call 401s.

2. **CSP `connect-src` must list your API origin.** The shipped CSP allows
   `https://*.railway.app` and `wss://*.railway.app`. If your backend is **not**
   on `*.railway.app`, edit `connect-src` in **both**
   [`infra/netlify.toml`](netlify.toml) and [`frontend/vercel.json`](../frontend/vercel.json)
   to your API's `https://` and `wss://` origins, or the browser blocks the fetch
   and the WebSocket.

Also set `CORS_ORIGINS` on the backend to the exact frontend URL (no trailing
slash, no `*` — `startup_check` rejects `*` in production).

---

## Optional: ship a trained model with the deploy

To have the email route return `score_source: "model"` in production:

```bash
cd backend
python scripts/fetch_datasets.py                                   # SpamAssassin
python scripts/train_email_classifier.py \
    --phishing data/email/spam --benign data/email/ham \
    --out models/email_classifier.joblib
```

Commit the `.joblib` to a private artifact store (it's gitignored by default) or
bake it into the image, then set `EMAIL_CLASSIFIER_PATH=/app/models/email_classifier.joblib`.

---

## Smoke test after deploy

```bash
curl https://<backend>/health                 # {"status":"ok"}
curl https://<backend>/ready                   # capabilities incl. "database": true
open  https://<backend>/docs                   # interactive API
open  https://<frontend>                        # the dashboard
```

If `/ready` shows `"database": false`, the schema wasn't applied or `DATABASE_URL`
is wrong. If the dashboard loads but shows a connection error, it's almost always
gotcha #1 or #2 above.
