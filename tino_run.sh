#!/usr/bin/env bash
#
# tino_run.sh — run a local TINO instance (development / demo).
#
# Authentication disabled, MCP enabled, bound to localhost only.
# Not for production use.
#
# Usage: ./tino_run.sh [start|stop|logs|restart]
#
set -euo pipefail

readonly CONTAINER=tino
readonly IMAGE="${TINO_IMAGE:-ghcr.io/confirm/tino}"   # pin a tag for reproducibility
readonly BIND="${TINO_BIND:-127.0.0.1:5000}"           # localhost only
readonly VOLUME="${TINO_VOLUME:-data}"                 # keeps your existing data
readonly BASE_URL="${TINO_BASE_URL:-http://localhost:5000}"
readonly SECRET_FILE="$(dirname "$0")/.tino-secret"

# Persist a secret key so sessions survive container restarts.
secret_key() {
  if [[ ! -s "$SECRET_FILE" ]]; then
    if command -v openssl >/dev/null 2>&1; then
      openssl rand -hex 32 >"$SECRET_FILE"
    else
      head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n' >"$SECRET_FILE"
    fi
  fi
  cat "$SECRET_FILE"
}

start() {
  command -v docker >/dev/null 2>&1 || { echo "docker not found" >&2; exit 1; }
  # Recreate so flag/env changes take effect; the named volume keeps the data.
  docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
  docker run -d \
    --name "$CONTAINER" \
    -e TINO_AUTH_DISABLED=true \
    -e TINO_BASE_URL="$BASE_URL" \
    -e TINO_MCP_ENABLED=true \
    -e TINO_SECRET_KEY="$(secret_key)" \
    -p "$BIND:5000" \
    -v "$VOLUME:/data" \
    --tmpfs /tmp \
    --read-only \
    --cap-drop ALL \
    --security-opt no-new-privileges:true \
    --restart unless-stopped \
    "$IMAGE"
  echo "TINO is starting → $BASE_URL"
}

case "${1:-start}" in
  start | restart) start ;;
  stop) docker rm -f "$CONTAINER" >/dev/null 2>&1 || true; echo "TINO stopped" ;;
  logs) docker logs -f "$CONTAINER" ;;
  *) echo "usage: $0 [start|stop|logs|restart]" >&2; exit 2 ;;
esac
