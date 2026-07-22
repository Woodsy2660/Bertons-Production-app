# Berton Bottling App — production image for BV-AZ-DockerHost01 (and local full-stack).
# Python 3.12 + WeasyPrint system libraries for PDF compilation fidelity.

FROM python:3.12-slim-bookworm AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# WeasyPrint native deps + fonts; curl for optional health probes
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpango-1.0-0 \
        libpangocairo-1.0-0 \
        libcairo2 \
        libgdk-pixbuf-2.0-0 \
        libffi-dev \
        shared-mime-info \
        fonts-dejavu-core \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies (core + WeasyPrint for Linux PDF quality)
COPY pyproject.toml ./
RUN pip install --upgrade pip \
    && pip install \
        "fastapi>=0.115.0" \
        "uvicorn[standard]>=0.32.0" \
        "sqlalchemy[asyncio]>=2.0.36" \
        "asyncpg>=0.30.0" \
        "alembic>=1.14.0" \
        "pydantic>=2.10.0" \
        "pydantic-settings>=2.6.0" \
        "jinja2>=3.1.0" \
        "python-multipart>=0.0.18" \
        "pypdf>=5.0.0" \
        "pdfplumber>=0.11.0" \
        "aiofiles>=24.0.0" \
        "itsdangerous>=2.2.0" \
        "xhtml2pdf>=0.2.16" \
        "httpx>=0.28.0" \
        "weasyprint>=62.0" \
        "pymupdf>=1.24.0" \
        "pillow>=10.0.0"

COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app
COPY scripts/docker-entrypoint.sh /docker-entrypoint.sh
# entrypoint must be executable as root before dropping privileges
RUN chmod +x /docker-entrypoint.sh \
    && mkdir -p /data/uploads /data/compiled \
    && useradd --create-home --shell /bin/bash appuser \
    && chown -R appuser:appuser /app /data

USER appuser

ENV UPLOAD_DIR=/data/uploads \
    COMPILED_OUTPUT_DIR=/data/compiled \
    STORAGE_BACKEND=local \
    DEBUG=false \
    SESSION_HTTPS_ONLY=false

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/ready || exit 1

ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
