# syntax=docker/dockerfile:1

# ---------- runtime: report generator, no dev/test deps ----------
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/src \
    OUTPUT_DIR=/app/output

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/

RUN mkdir -p /app/output

ENTRYPOINT ["python", "-m", "espn_digest.cli"]
CMD []

# ---------- test: runtime + pytest + the suite ----------
FROM runtime AS test

COPY requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements-dev.txt

COPY tests/ ./tests/
COPY pytest.ini ./

ENTRYPOINT ["python", "-m", "pytest"]
CMD ["-q"]
