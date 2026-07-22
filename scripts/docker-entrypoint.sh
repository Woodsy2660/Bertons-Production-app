#!/bin/sh
set -e

echo "Running Alembic migrations (with retry)..."
i=0
until python -m alembic upgrade head; do
  i=$((i + 1))
  if [ "$i" -ge 30 ]; then
    echo "ERROR: migrations failed after ${i} attempts" >&2
    exit 1
  fi
  echo "Database not ready (attempt $i/30); retrying in 2s..."
  sleep 2
done
echo "Migrations complete."

echo "Starting application: $*"
exec "$@"
