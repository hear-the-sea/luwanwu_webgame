#!/usr/bin/env bash
set -euo pipefail

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_DIR="${BASE_DIR}/runtime"

mkdir -p \
  "${RUNTIME_DIR}/media/guests" \
  "${RUNTIME_DIR}/media/items" \
  "${RUNTIME_DIR}/media/troops" \
  "${RUNTIME_DIR}/staticfiles" \
  "${RUNTIME_DIR}/celerybeat"

# Use permissive mode to avoid UID/GID mismatch issues across hosts/runtimes.
chmod -R a+rwX "${RUNTIME_DIR}/media" "${RUNTIME_DIR}/staticfiles" "${RUNTIME_DIR}/celerybeat"

echo "Prepared runtime directories under ${RUNTIME_DIR}"
