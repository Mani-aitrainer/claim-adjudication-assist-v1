# syntax=docker/dockerfile:1

# ---- builder ----------------------------------------------------------
FROM python:3.12-slim AS builder

WORKDIR /build

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src/ ./src/

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir --no-compile --prefix=/install ".[local]" \
    && find /install -name '__pycache__' -type d -exec rm -rf {} + \
    && rm -rf /install/lib/python*/site-packages/pip* /install/lib/python*/site-packages/setuptools*

# ---- test (used by `make docker-test` / CI, not shipped) ----------------
FROM builder AS test

RUN pip install ".[local,testdata,dev]"

COPY tests/ ./tests/
COPY testdata/ ./testdata/
COPY pipelines/ ./pipelines/
COPY scripts/ ./scripts/
COPY config/ ./config/
COPY domains/ ./domains/

ENV PYTHONPATH=/build/src \
    PYTHONUNBUFFERED=1

# data/policies/*.pdf is gitignored (generated, not committed) — regenerate it here so
# the test image is self-contained and doesn't depend on host-machine build state.
RUN python -m testdata.generate policies

CMD ["python", "-m", "pytest", "-q"]

# ---- runtime ------------------------------------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/usr/local/bin:$PATH"

RUN groupadd --system appuser && useradd --system --gid appuser --create-home appuser

WORKDIR /app

COPY --from=builder /install /usr/local
COPY src/ ./src/
COPY config/ ./config/
COPY domains/ ./domains/
COPY docker/entrypoint.sh /entrypoint.sh

RUN chmod +x /entrypoint.sh \
    && mkdir -p /app/.local /app/data/documents \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz', timeout=3)" || exit 1

ENTRYPOINT ["/entrypoint.sh"]
