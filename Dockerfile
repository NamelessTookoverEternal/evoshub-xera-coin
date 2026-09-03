# EVOS Business Hub / XERA Token — FastAPI backend
#
# Container image build context is the repo root (works for Fly.io,
# Google Cloud Run, or any Docker-based host). Everything the app
# needs is copied in from ./python explicitly below.
#
# Explicit Dockerfile so the platform never has to guess the
# framework by scanning requirements.txt. The backend is FastAPI +
# uvicorn — not Flask. (Ignore any unrelated Flask/gunicorn
# requirements.txt elsewhere in the repo; it's not used by this image.)

FROM python:3.12-slim

WORKDIR /app

# System deps needed by some wheels (bcrypt/passlib build chain on slim images)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY python/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY python/ .

# Fly injects $PORT; Cloud Run does too. Default to 8080 for local `docker run`.
ENV PORT=8080
EXPOSE 8080

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT}"]
