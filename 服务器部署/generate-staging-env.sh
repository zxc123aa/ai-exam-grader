#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATE="$SCRIPT_DIR/.env.staging.example"
OUTPUT="${1:-$SCRIPT_DIR/.env.staging}"

if [[ -e "$OUTPUT" ]]; then
  echo "Refusing to overwrite existing environment file: $OUTPUT" >&2
  exit 1
fi

umask 077
secret_key="$(openssl rand -hex 48)"
superuser_password="$(openssl rand -hex 16)"
postgres_password="$(openssl rand -hex 24)"
provider_key="$(openssl rand -base64 32 | tr '+/' '-_' | tr -d '\n')"

while IFS= read -r line || [[ -n "$line" ]]; do
  case "$line" in
    SECRET_KEY=*) line="SECRET_KEY=$secret_key" ;;
    FIRST_SUPERUSER_PASSWORD=*) line="FIRST_SUPERUSER_PASSWORD=$superuser_password" ;;
    POSTGRES_PASSWORD=*) line="POSTGRES_PASSWORD=$postgres_password" ;;
    PROVIDER_CREDENTIAL_MASTER_KEY=*)
      line="PROVIDER_CREDENTIAL_MASTER_KEY=$provider_key"
      ;;
  esac
  printf '%s\n' "$line"
done < "$TEMPLATE" > "$OUTPUT"

chmod 600 "$OUTPUT"
echo "Created staging environment: $OUTPUT"
