#!/usr/bin/env bash
# Deploy / re-host the bottling app on BV-AZ-DockerHost01.
# Usage:
#   ./scripts/deploy.sh              # build + up with current tree / APP_TAG
#   ./scripts/deploy.sh v1.2.3       # set APP_TAG and pull/build that tag
#   ./scripts/deploy.sh --pull-only  # pull pre-built image (no local build)
#
# Project must live under /home/azureuser/ (snap Docker confinement).

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PULL_ONLY=0
TAG="${APP_TAG:-latest}"

for arg in "$@"; do
  case "$arg" in
    --pull-only) PULL_ONLY=1 ;;
    -h|--help)
      sed -n '2,12p' "$0"
      exit 0
      ;;
    *) TAG="$arg" ;;
  esac
done

export APP_TAG="$TAG"

if [[ ! -f .env ]]; then
  echo "ERROR: .env missing. Copy .env.example → .env and set production secrets."
  exit 1
fi

# shellcheck disable=SC1091
set -a
# shellcheck source=/dev/null
source .env
set +a

if [[ "${DEBUG:-}" == "true" ]]; then
  echo "WARNING: DEBUG=true in .env — not recommended on the floor."
fi

echo "==> Deploying berton-bottling-app (APP_TAG=$APP_TAG)"

if [[ "$PULL_ONLY" -eq 1 ]]; then
  echo "==> Pulling images"
  docker compose --profile full pull
  docker compose --profile full up -d --no-build
else
  echo "==> Building and starting (profile: full)"
  docker compose --profile full up -d --build
fi

echo "==> Waiting for readiness..."
ok=0
for i in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:${APP_PORT:-8000}/ready" >/dev/null 2>&1; then
    ok=1
    break
  fi
  sleep 2
done

if [[ "$ok" -ne 1 ]]; then
  echo "ERROR: /ready did not become healthy. Recent logs:"
  docker compose --profile full logs --tail=80 web || true
  exit 1
fi

echo "==> Healthy:"
curl -sS "http://127.0.0.1:${APP_PORT:-8000}/health" || true
echo
curl -sS "http://127.0.0.1:${APP_PORT:-8000}/ready" || true
echo
echo "Done. Tablets: http://10.0.0.4:${APP_PORT:-8000}"
