# syntax=docker/dockerfile:1
FROM python:3.12-slim-bookworm

# Prevent Python from buffering stdout/stderr (useful for container logs)
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    # uv settings
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

# Install system dependencies for WeasyPrint, pikepdf (qpdf), and fonts
RUN apt-get update && apt-get install -y --no-install-recommends \
    # WeasyPrint dependencies
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libcairo2 \
    libgdk-pixbuf-2.0-0 \
    libffi-dev \
    # pikepdf/qpdf dependency
    qpdf \
    # Fonts for PDF rendering
    fonts-dejavu-core \
    fonts-liberation \
    # Clean up
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Create non-root user for security
RUN useradd --create-home --shell /bin/bash appuser

WORKDIR /app

# Copy dependency files first for better caching
COPY pyproject.toml uv.lock ./

# Install dependencies using frozen lockfile (reproducible builds)
RUN uv sync --frozen --no-dev

# Copy application code
COPY alembic.ini ./
COPY alembic/ ./alembic/
COPY app/ ./app/
COPY main.py ./

# Copy and set up entrypoint script
COPY entrypoint.sh ./
RUN chmod +x entrypoint.sh

# Create directories for uploads and compiled output
RUN mkdir -p uploads compiled_output pallet_tags \
    && chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

EXPOSE 8000

ENTRYPOINT ["./entrypoint.sh"]
