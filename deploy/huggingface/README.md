# Deploy the backend on Hugging Face Spaces (free, no card)

Hugging Face Spaces runs Docker containers for free with no payment method. This
folder has the one file you need: a self-contained `Dockerfile` that clones the
public repo and runs the slim API.

## Steps

1. **Create a free Hugging Face account** — <https://huggingface.co/join> (no card).
2. **New Space** — <https://huggingface.co/new-space>:
   - Owner: you · Space name: `cerebro-api`
   - **Space SDK: Docker** → **Blank**
   - Visibility: Public (free)
   - Create.
3. The new Space opens on its **Files** tab with a `README.md` already created.
   Click **Add file → Create a new file**, name it `Dockerfile`, and paste the
   contents of [`Dockerfile`](Dockerfile) from this folder. Commit.
4. **Settings → Variables and secrets** — add these (use *Secret* for the first
   three, *Variable* for the rest):

   | Name | Value |
   |---|---|
   | `DATABASE_URL` | your Neon connection string (see below) |
   | `SECRET_KEY` | a long random string (`python -c "import secrets;print(secrets.token_urlsafe(48))"`) |
   | `TOKEN_ENCRYPTION_KEY` | another one (`...token_urlsafe(32)`) |
   | `ENVIRONMENT` | `production` |
   | `AUTO_APPLY_SCHEMA` | `true` |
   | `SEED_DEMO_USER` | `true` |
   | `SESSION_COOKIE_SAMESITE` | `none` |
   | `LLM_PROVIDER` | `template` |
   | `CORS_ORIGINS` | your Vercel URL (set after the frontend deploys) |

5. The Space rebuilds automatically after you add the Dockerfile. When it shows
   **Running**, your API is at `https://<you>-cerebro-api.hf.space`.
   Check `https://<you>-cerebro-api.hf.space/health` → `{"status":"ok"}`.

## Neon (the free database, no card)

1. <https://neon.tech> → sign up (no card) → **New Project** (Postgres 16).
2. Copy the **connection string** it shows
   (`postgresql://user:pass@...neon.tech/dbname?sslmode=require`).
3. Paste it as `DATABASE_URL` in the Space secrets above. `AUTO_APPLY_SCHEMA=true`
   creates the tables and the pgvector extension on first boot; `SEED_DEMO_USER`
   creates the demo login.

Login once it's all up: `demo@cerebro.app` / `cerebro-demo-2026`.
