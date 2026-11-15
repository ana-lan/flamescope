# IgnitIQ API: FastAPI + DuckDB + fastembed, built for Render.
FROM python:3.11-slim

COPY --from=ghcr.io/astral-sh/uv:0.13.8 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON=/usr/local/bin/python3 \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1

WORKDIR /app

# 1. Dependencies only. Cached until pyproject.toml or uv.lock change.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
ENV PATH="/app/.venv/bin:$PATH"

# 2. Bake the embedding model into the image (same name and folder rag.py uses).
#    Placed before the code copy, so code edits do not re-download it.
RUN python -c "from fastembed import TextEmbedding; \
TextEmbedding(model_name='BAAI/bge-small-en-v1.5', cache_dir='/app/.cache/fastembed')"

# 3. Code and the committed data in data/processed/.
COPY . .
RUN uv sync --frozen --no-dev

# 4. From here on, never reach the internet for the model.
ENV HF_HUB_OFFLINE=1

# 5. Fail the build if the app cannot start without raw data or network.
RUN python -c "from ignitiq import rag; from ignitiq.db import connect; \
print('embed', rag.embed_query('warm up').shape); rag.load_index(); print('index ok'); \
print('tests', connect().execute('select count(*) from tests').fetchone()[0])"

EXPOSE 8000
CMD ["sh", "-c", "uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]