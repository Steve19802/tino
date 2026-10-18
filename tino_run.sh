#!/usr/bin/env bash
#
# tino_run.sh — run a local TINO instance (development / demo).
#
# Authentication disabled, MCP enabled, bound to localhost only.
# Not for production use.
#
# Usage: ./tino_run.sh [start|build|stop|logs|restart]
#
#   start    Run the image (pulled from the registry on first use).
#   build    Build the image from source with make, then run it.
#   restart  Recreate the container from the current image.
#   logs     Follow the container logs.
#   stop     Remove the container.
#
# Env overrides: TINO_IMAGE, TINO_BIND, TINO_VOLUME, TINO_BASE_URL,
# TINO_BUILD_TARGETS.
#
set -euo pipefail

readonly SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
readonly CONTAINER=tino
readonly IMAGE="${TINO_IMAGE:-ghcr.io/confirm/tino}"   # pin a tag for reproducibility
readonly BIND="${TINO_BIND:-127.0.0.1:5000}"           # localhost only
readonly VOLUME="${TINO_VOLUME:-data}"                 # keeps your existing data
readonly BASE_URL="${TINO_BASE_URL:-http://localhost:5000}"
readonly SECRET_FILE="$SCRIPT_DIR/.tino-secret"
# Registry tag `make docker-image` produces; see the Makefile / CI workflow.
readonly BUILD_TAG=ghcr.io/confirm/tino
# Make targets that build the image from source (order matters: vendor-*
# must run before `package`, which bundles them into the wheel the
# Dockerfile copies).
readonly BUILD_TARGETS="${TINO_BUILD_TARGETS:-vendor-css vendor-js package docker-image}"

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

# Build the image from source via make (frontend bundle, wheel, docker build).
build() {
  command -v make >/dev/null 2>&1 || { echo "make not found" >&2; exit 1; }
  # `make package` writes a versioned wheel per commit; stale ones accumulate in
  # build/ and the Dockerfile's `COPY build/*.whl` copies them all, which makes
  # `pip install *.whl` fail on conflicting tino versions. Keep only the one
  # we're about to build.
  rm -f "$SCRIPT_DIR"/build/*.whl
  echo "Building TINO image from source: make $BUILD_TARGETS"
  make -C "$SCRIPT_DIR" $BUILD_TARGETS
  # `make docker-image` tags the build as $BUILD_TAG; re-tag if running
  # under a different TINO_IMAGE.
  if [[ "$IMAGE" != "$BUILD_TAG" ]]; then
    docker tag "$BUILD_TAG" "$IMAGE"
  fi
  echo "Built image: $IMAGE"
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
  build) build && start ;;
  stop) docker rm -f "$CONTAINER" >/dev/null 2>&1 || true; echo "TINO stopped" ;;
  logs) docker logs -f "$CONTAINER" ;;
  *) echo "usage: $0 [start|build|stop|logs|restart]" >&2; exit 2 ;;
esac
