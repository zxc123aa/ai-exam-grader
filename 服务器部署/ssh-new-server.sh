#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
CREDENTIAL_FILE="$SCRIPT_DIR/.env"

if [[ ! -f "$CREDENTIAL_FILE" ]]; then
  echo "Missing credential file: $CREDENTIAL_FILE" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "$CREDENTIAL_FILE"
set +a

: "${NEW_SERVER_HOST:?NEW_SERVER_HOST is required}"
: "${NEW_SERVER_PORT:?NEW_SERVER_PORT is required}"
: "${NEW_SERVER_USER:?NEW_SERVER_USER is required}"
: "${NEW_SERVER_PASSWORD:?NEW_SERVER_PASSWORD is required}"

SSH_OPTIONS=(
  -o StrictHostKeyChecking=accept-new
  -o ConnectTimeout=15
  -o ServerAliveInterval=30
  -o ServerAliveCountMax=3
)

if [[ -n "${NEW_SERVER_SOCKS_PROXY:-}" ]]; then
  SSH_OPTIONS+=(
    -o "ProxyCommand=nc -X 5 -x ${NEW_SERVER_SOCKS_PROXY} %h %p"
  )
fi

ASKPASS_FILE="$(mktemp)"
cleanup() {
  unset NEW_SERVER_PASSWORD
  unlink "$ASKPASS_FILE" 2>/dev/null || true
}
trap cleanup EXIT

chmod 700 "$ASKPASS_FILE"
printf '#!/bin/sh\nprintf "%%s\\n" "$NEW_SERVER_PASSWORD"\n' >"$ASKPASS_FILE"

export DISPLAY="${DISPLAY:-:0}"
export SSH_ASKPASS="$ASKPASS_FILE"
export SSH_ASKPASS_REQUIRE=force

ssh \
  "${SSH_OPTIONS[@]}" \
  -p "$NEW_SERVER_PORT" \
  "$NEW_SERVER_USER@$NEW_SERVER_HOST" \
  "$@"
