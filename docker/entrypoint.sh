#!/usr/bin/env bash
set -euo pipefail

export DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-config.settings}"

python - <<'PY'
import os
import time

import django
from django.db import connections
from django.db.utils import OperationalError

os.environ.setdefault("DJANGO_SETTINGS_MODULE", os.environ.get("DJANGO_SETTINGS_MODULE", "config.settings"))
django.setup()

deadline = time.time() + int(os.environ.get("DJANGO_WAIT_FOR_DB_SECONDS", "60"))
while True:
    try:
        connections["default"].ensure_connection()
        break
    except OperationalError as exc:
        if time.time() > deadline:
            raise
        print(f"[entrypoint] waiting for db... ({exc})")
        time.sleep(1)
PY

python - <<'PY'
import os
import time

import django
from django.core.cache import cache

os.environ.setdefault("DJANGO_SETTINGS_MODULE", os.environ.get("DJANGO_SETTINGS_MODULE", "config.settings"))
django.setup()

deadline = time.time() + int(os.environ.get("DJANGO_WAIT_FOR_REDIS_SECONDS", "60"))
key = "startup:cache:ping"
while True:
    try:
        cache.set(key, "1", timeout=5)
        if cache.get(key) == "1":
            break
    except Exception as exc:
        if time.time() > deadline:
            print(f"[entrypoint] cache/redis not ready after timeout, continuing... ({exc})")
            break
        print(f"[entrypoint] waiting for cache/redis... ({exc})")
        time.sleep(1)
PY

if [[ "${DJANGO_RUN_MIGRATIONS:-0}" == "1" ]]; then
  python manage.py migrate --noinput
fi

if [[ "${DJANGO_COLLECTSTATIC:-0}" == "1" ]]; then
  python manage.py collectstatic --noinput
fi

exec "$@"
