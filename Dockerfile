# EasyLearn — production-style image (uv + Python 3.14)
FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

# Optional extras (empty by default). Examples:
#   --build-arg UV_EXTRAS="--extra ocr"
#   --build-arg UV_EXTRAS="--extra ocr --extra rag"
ARG UV_EXTRAS=

# Install dependencies first (layer cache)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project ${UV_EXTRAS}

COPY app ./app
COPY main.py ./
COPY config ./config
COPY static ./static
COPY templates ./templates

RUN uv sync --frozen --no-dev ${UV_EXTRAS}

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
