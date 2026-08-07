#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "Usage: $0 <release-tag> <config|infra|build|app|status|logs>" >&2
  exit 1
fi

TAG="$1"
ACTION="$2"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
DEPLOY_ROOT="${DIANFAN_DEPLOY_ROOT:-/opt/dianfan-grading}"
SHARED_DIR="$DEPLOY_ROOT/shared"
COMPOSE_FILE="$SCRIPT_DIR/compose.staging.yml"

export TAG
export DIANFAN_ENV_FILE="${DIANFAN_ENV_FILE:-$SHARED_DIR/.env.staging}"
export DIANFAN_REFERENCE_ENV_FILE="${DIANFAN_REFERENCE_ENV_FILE:-$SHARED_DIR/.env.reference-algorithm}"
export DIANFAN_UPLOADS_DIR="${DIANFAN_UPLOADS_DIR:-$SHARED_DIR/uploads}"

if [[ ! -f "$DIANFAN_ENV_FILE" ]]; then
  echo "Missing staging environment: $DIANFAN_ENV_FILE" >&2
  exit 1
fi

compose=(
  docker compose
  --project-name dianfan-staging
  --env-file "$DIANFAN_ENV_FILE"
  --project-directory "$PROJECT_ROOT"
  -f "$COMPOSE_FILE"
)

case "$ACTION" in
  config)
    "${compose[@]}" config --quiet
    ;;
  infra)
    mkdir -p "$DIANFAN_UPLOADS_DIR"
    "${compose[@]}" up -d db redis
    ;;
  build)
    "${compose[@]}" build --pull prestart frontend reference-algorithm
    ;;
  app)
    "${compose[@]}" up -d --remove-orphans
    ;;
  status)
    "${compose[@]}" ps
    ;;
  logs)
    "${compose[@]}" logs --tail=200 backend worker prestart
    ;;
  *)
    echo "Unknown action: $ACTION" >&2
    exit 1
    ;;
esac
