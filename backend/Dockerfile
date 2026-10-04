# Local packaging (M9.4) — runs the FastAPI app shell (M2.1) on :8000.
#
# Base install only, to keep the image lean. The optional `ml` extra (faster-whisper,
# sentence-transformers, chromadb) pulls heavy CPU torch; clustering / memory / verdicts
# degrade gracefully without it (run.py typed-skips). For the full feature set, the
# recommended path is local on a Mac (Metal) via scripts/dev.sh, not this container.
FROM python:3.11-slim

WORKDIR /app
COPY pyproject.toml ./
RUN pip install --no-cache-dir .

COPY app ./app
RUN mkdir -p data  # local SQLite + Chroma + frames (bind-mounted in docker-compose)

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
