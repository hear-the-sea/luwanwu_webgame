"""
Database and cache configuration.
"""
from __future__ import annotations

from urllib.parse import quote, urlparse, urlunparse

from .base import BASE_DIR, DEBUG, env


# Redis configuration
REDIS_URL = env("REDIS_URL", "redis://127.0.0.1:6379")
REDIS_PASSWORD = env("REDIS_PASSWORD", "")


def _redis_url_with_password(url: str, password: str) -> str:
    """Inject password into a redis:// URL if it has no auth part."""
    if not password:
        return url

    parsed = urlparse(url)
    if parsed.scheme not in {"redis", "rediss"}:
        return url

    if "@" in (parsed.netloc or ""):
        return url

    host = parsed.hostname or ""
    port = f":{parsed.port}" if parsed.port else ""
    auth = f":{quote(password, safe='')}@"
    netloc = f"{auth}{host}{port}"
    return urlunparse(parsed._replace(netloc=netloc))


# Production security: warn if Redis password is not set
if not DEBUG and not REDIS_PASSWORD:
    import warnings
    warnings.warn(
        "REDIS_PASSWORD is not set in production. "
        "This is a security risk. Set REDIS_PASSWORD environment variable.",
        RuntimeWarning
    )

REDIS_BROKER_URL = _redis_url_with_password(env("REDIS_BROKER_URL", f"{REDIS_URL}/0"), REDIS_PASSWORD)
REDIS_RESULT_URL = _redis_url_with_password(env("REDIS_RESULT_URL", REDIS_BROKER_URL), REDIS_PASSWORD)
REDIS_CHANNEL_URL = _redis_url_with_password(env("REDIS_CHANNEL_URL", f"{REDIS_URL}/1"), REDIS_PASSWORD)
REDIS_CACHE_URL = _redis_url_with_password(env("REDIS_CACHE_URL", f"{REDIS_URL}/2"), REDIS_PASSWORD)

# Redis cache configuration
_redis_cache_options = {
    "CLIENT_CLASS": "django_redis.client.DefaultClient",
}
if REDIS_PASSWORD:
    _redis_cache_options["PASSWORD"] = REDIS_PASSWORD

CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": REDIS_CACHE_URL,
        "OPTIONS": _redis_cache_options,
    }
}

# Database engine configuration
_db_engine = env("DJANGO_DB_ENGINE", "django.db.backends.sqlite3")

# Connection pool configuration
_conn_max_age_str = env("DJANGO_DB_CONN_MAX_AGE", "")
if _conn_max_age_str.lower() == "none":
    _conn_max_age = None
elif _conn_max_age_str:
    _conn_max_age = int(_conn_max_age_str)
else:
    _conn_max_age = 60 if DEBUG else 300

# Database-specific options
_db_options = {}
if "postgresql" in _db_engine:
    _db_options = {
        "connect_timeout": 5,
        "application_name": "webgame_v5",
        "sslmode": env("DJANGO_DB_SSLMODE", "prefer"),
    }
elif "mysql" in _db_engine:
    _db_options = {
        "connect_timeout": 5,
        "init_command": "SET sql_mode='STRICT_TRANS_TABLES'",
    }

DATABASES = {
    "default": {
        "ENGINE": _db_engine,
        "NAME": env("DJANGO_DB_NAME", str(BASE_DIR / "db.sqlite3")),
        "USER": env("DJANGO_DB_USER", ""),
        "PASSWORD": env("DJANGO_DB_PASSWORD", ""),
        "HOST": env("DJANGO_DB_HOST", ""),
        "PORT": env("DJANGO_DB_PORT", ""),
        "CONN_MAX_AGE": _conn_max_age,
        "CONN_HEALTH_CHECKS": env("DJANGO_DB_CONN_HEALTH_CHECKS", "1") == "1",
        "DISABLE_SERVER_SIDE_CURSORS": env("DJANGO_DB_DISABLE_SERVER_SIDE_CURSORS", "") == "1",
        "OPTIONS": _db_options,
    }
}

# Channel layers
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {"hosts": [REDIS_CHANNEL_URL]},
    },
}
