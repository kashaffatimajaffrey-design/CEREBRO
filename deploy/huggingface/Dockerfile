# Hugging Face Space (Docker SDK) — backend for CEREBRO.
#
# This is self-contained: it clones the public GitHub repo at build time and
# runs the slim API. So the Space only needs THIS one file — you don't push the
# whole codebase to the Space. HF Spaces must listen on port 7860.
#
# To update after you push new code to GitHub: open the Space → Settings →
# "Factory rebuild" (a plain restart won't re-clone).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        git build-essential curl libgomp1 && rm -rf /var/lib/apt/lists/*

# Clone the app. Pin to main; bump this comment to force a rebuild if needed. (v1)
RUN git clone --depth 1 https://github.com/kashaffatimajaffrey-design/CEREBRO.git /app

WORKDIR /app/backend
RUN pip install --no-cache-dir -r requirements-serve.txt

# HF Spaces route traffic to port 7860.
ENV PORT=7860
EXPOSE 7860
CMD ["sh", "-c", "uvicorn services.api.main:app --host 0.0.0.0 --port 7860"]
