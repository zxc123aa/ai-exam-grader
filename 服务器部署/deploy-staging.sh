#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "Usage: $0 <release-tag> <config|infra|build|pull|app|status|logs>" >&2
  echo "  build: 在本机构建镜像；pull: 拉取 CI 发布的镜像（需先设置 DIANFAN_IMAGE_*）" >&2
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
# 显式转发，避免调用方只在 shell 里赋值而没 export 时静默回落到本地镜像名。
export DIANFAN_IMAGE_BACKEND="${DIANFAN_IMAGE_BACKEND:-}"
export DIANFAN_IMAGE_FRONTEND="${DIANFAN_IMAGE_FRONTEND:-}"
export DIANFAN_IMAGE_REFERENCE="${DIANFAN_IMAGE_REFERENCE:-}"
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
  pull)
    # 用 CI 发布的不可变镜像替代本机构建。需要先 docker login ghcr.io，
    # 并把 DIANFAN_IMAGE_BACKEND/FRONTEND/REFERENCE 指到 registry 全名，
    # 否则这里只会去拉本地镜像名而失败。
    # 三个都要设。只设一部分会让另一部分带着本地镜像名去 registry 拉取，
    # 报错信息很难看懂。
    missing=()
    for var in DIANFAN_IMAGE_BACKEND DIANFAN_IMAGE_FRONTEND DIANFAN_IMAGE_REFERENCE; do
      [[ -z "${!var:-}" ]] && missing+=("$var")
    done
    if [[ ${#missing[@]} -gt 0 ]]; then
      echo "pull 需要设置：${missing[*]}" >&2
      echo "例如 export DIANFAN_IMAGE_BACKEND=ghcr.io/zxc123aa/dianfan-backend" >&2
      exit 1
    fi
    "${compose[@]}" pull backend worker prestart frontend reference-algorithm
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
