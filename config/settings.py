from __future__ import annotations

import math
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from kombu import Queue
from celery.schedules import crontab


BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")


def env(key: str, default: str = "") -> str:
    return os.getenv(key, default)

try:
    GAME_TIME_MULTIPLIER = float(env("GAME_TIME_MULTIPLIER", "1") or "1")
except (TypeError, ValueError):
    GAME_TIME_MULTIPLIER = 1.0
if not math.isfinite(GAME_TIME_MULTIPLIER) or GAME_TIME_MULTIPLIER <= 0:
    GAME_TIME_MULTIPLIER = 1.0


# Security: SECRET_KEY must be set via environment variable in production
# For development, you can use .env file with a secure random key
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY")
if not SECRET_KEY:
    # Development fallback - fail fast in production
    if not env("DJANGO_DEBUG", "0") == "1":
        raise RuntimeError(
            "DJANGO_SECRET_KEY must be set in environment for production. "
            "Generate one with: python -c 'from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())'"
        )
    # Development mode: generate random key for this session
    import warnings
    from django.core.management.utils import get_random_secret_key
    SECRET_KEY = get_random_secret_key()
    warnings.warn(
        f"DJANGO_SECRET_KEY not set. Using temporary random key for development only. "
        f"Add this to your .env file:\nDJANGO_SECRET_KEY={SECRET_KEY}",
        RuntimeWarning
    )

# DEBUG should default to False for security
DEBUG = env("DJANGO_DEBUG", "0") == "1"

# ALLOWED_HOSTS: Never allow "*" in production
# Must be explicitly set via DJANGO_ALLOWED_HOSTS environment variable
allowed_hosts_str = env("DJANGO_ALLOWED_HOSTS", "")
ALLOWED_HOSTS = []
if allowed_hosts_str:
    ALLOWED_HOSTS = [
        host.strip()
        for host in allowed_hosts_str.split(",")
        if host.strip() and host.strip() != "*"
    ]

# Production validation: ALLOWED_HOSTS must be set
if not DEBUG and not ALLOWED_HOSTS:
    raise RuntimeError(
        "ALLOWED_HOSTS must be set in production environment. "
        "Set DJANGO_ALLOWED_HOSTS in your environment with comma-separated domains."
    )

# Development fallback: allow localhost if DEBUG is True
if DEBUG and not ALLOWED_HOSTS:
    ALLOWED_HOSTS = ["localhost", "127.0.0.1"]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "channels",
    "accounts",
    "gameplay",
    "guests",
    "battle",
    "trade",
    "guilds",
    "battle_debugger",  # 战斗调试工具
]

MIDDLEWARE = [
    "core.middleware.RequestIDMiddleware",  # 请求追踪
    "core.middleware.AccessLogMiddleware",  # 访问日志
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "gameplay.context_processors.notifications",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

REDIS_URL = env("REDIS_URL", "redis://127.0.0.1:6379")
REDIS_BROKER_URL = env("REDIS_BROKER_URL", f"{REDIS_URL}/0")
REDIS_RESULT_URL = env("REDIS_RESULT_URL", REDIS_BROKER_URL)
REDIS_CHANNEL_URL = env("REDIS_CHANNEL_URL", f"{REDIS_URL}/1")
REDIS_CACHE_URL = env("REDIS_CACHE_URL", f"{REDIS_URL}/2")

CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": REDIS_CACHE_URL,
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
        }
    }
}

# 数据库引擎配置
_db_engine = env("DJANGO_DB_ENGINE", "django.db.backends.sqlite3")

# 连接池配置：启用持久连接以减少建连开销
# - None: 永不关闭连接（适合PgBouncer等外部连接池）
# - 60: 开发环境默认（60秒）
# - 300-600: 生产环境推荐（5-10分钟）
_conn_max_age_str = env("DJANGO_DB_CONN_MAX_AGE", "")
if _conn_max_age_str.lower() == "none":
    _conn_max_age = None
elif _conn_max_age_str:
    _conn_max_age = int(_conn_max_age_str)
else:
    _conn_max_age = 60 if DEBUG else 300

# 根据数据库引擎配置OPTIONS（避免无效参数导致错误）
_db_options = {}
if "postgresql" in _db_engine:
    # PostgreSQL特定配置
    _db_options = {
        "connect_timeout": 5,
        "application_name": "webgame_v5",
        "sslmode": env("DJANGO_DB_SSLMODE", "prefer"),
    }
elif "mysql" in _db_engine:
    # MySQL特定配置
    _db_options = {
        "connect_timeout": 5,
        "init_command": "SET sql_mode='STRICT_TRANS_TABLES'",
    }
# SQLite不需要OPTIONS配置

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
        # 禁用服务器端游标（适用于PgBouncer的transaction模式）
        # 仅对PostgreSQL生效，其他数据库会忽略此选项
        "DISABLE_SERVER_SIDE_CURSORS": env("DJANGO_DB_DISABLE_SERVER_SIDE_CURSORS", "") == "1",
        "OPTIONS": _db_options,
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "zh-hans"
TIME_ZONE = "Asia/Shanghai"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static", BASE_DIR / "data" / "images"]
STATIC_ROOT = BASE_DIR / "staticfiles"

# 媒体文件配置（用户上传的图片等）
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_USER_MODEL = "accounts.User"

LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/"
LOGIN_URL = "accounts:login"

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

REST_FRAMEWORK = {
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
        # BasicAuthentication removed for security (credentials sent in plaintext)
        # If needed for API clients, use token-based auth over HTTPS only
    ],
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": "100/hour",  # Anonymous users: 100 requests per hour
        "user": "1000/hour",  # Authenticated users: 1000 requests per hour
        "recruit": "20/hour",  # Guest recruitment: 20 per hour
        "battle": "100/hour",  # Battle/mission: 100 per hour
        "claim": "50/hour",  # Claim attachments: 50 per hour
    },
}

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {"hosts": [REDIS_CHANNEL_URL]},
    },
}

CELERY_BROKER_URL = env("CELERY_BROKER_URL", REDIS_BROKER_URL)
CELERY_RESULT_BACKEND = env(
    "CELERY_RESULT_BACKEND",
    CELERY_BROKER_URL if "CELERY_BROKER_URL" in os.environ else REDIS_RESULT_URL,
)
CELERY_DEFAULT_QUEUE = env("CELERY_DEFAULT_QUEUE", "default")
CELERY_BATTLE_QUEUE = env("CELERY_BATTLE_QUEUE", "battle")
CELERY_TIMER_QUEUE = env("CELERY_TIMER_QUEUE", "timer")
CELERY_TASK_DEFAULT_QUEUE = CELERY_DEFAULT_QUEUE
CELERY_TASK_QUEUES = (
    Queue(CELERY_DEFAULT_QUEUE),
    Queue(CELERY_BATTLE_QUEUE),
    Queue(CELERY_TIMER_QUEUE),
)
CELERY_TASK_ROUTES = {
    "battle.generate_report": {"queue": CELERY_BATTLE_QUEUE},
    "gameplay.complete_mission": {"queue": CELERY_TIMER_QUEUE},
    "gameplay.complete_building_upgrade": {"queue": CELERY_TIMER_QUEUE},
    "gameplay.scan_building_upgrades": {"queue": CELERY_TIMER_QUEUE},
    "gameplay.complete_work_assignments": {"queue": CELERY_TIMER_QUEUE},
    "guests.complete_training": {"queue": CELERY_TIMER_QUEUE},
    "guests.scan_training": {"queue": CELERY_TIMER_QUEUE},
    # 侦察和踢馆系统任务
    "gameplay.complete_scout": {"queue": CELERY_TIMER_QUEUE},
    "gameplay.scan_scout_records": {"queue": CELERY_TIMER_QUEUE},
    "gameplay.process_raid_battle": {"queue": CELERY_TIMER_QUEUE},
    "gameplay.complete_raid": {"queue": CELERY_TIMER_QUEUE},
    "gameplay.scan_raid_runs": {"queue": CELERY_TIMER_QUEUE},
}
CELERY_BEAT_SCHEDULE = {
    "scan-building-upgrades": {
        "task": "gameplay.scan_building_upgrades",
        "schedule": crontab(minute="*/10"),
    },
    "scan-guest-training": {
        "task": "guests.scan_training",
        "schedule": crontab(minute="*/10"),
    },
    "complete-work-assignments": {
        "task": "gameplay.complete_work_assignments",
        "schedule": crontab(minute="*/1"),  # 每分钟执行一次
    },
    "refresh-shop-stock": {
        "task": "trade.refresh_shop_stock",
        "schedule": crontab(hour=0, minute=0),
    },
    # 帮会系统定时任务
    "guild-tech-daily-production": {
        "task": "guilds.tech_daily_production",
        "schedule": crontab(hour=0, minute=0),  # 每天00:00
    },
    "reset-guild-weekly-stats": {
        "task": "guilds.reset_weekly_stats",
        "schedule": crontab(hour=0, minute=0, day_of_week=1),  # 每周一00:00
    },
    "cleanup-old-guild-logs": {
        "task": "guilds.cleanup_old_logs",
        "schedule": crontab(hour=3, minute=0),  # 每天03:00
    },
    # 侦察和踢馆系统扫描任务（Worker宕机恢复用）
    "scan-scout-records": {
        "task": "gameplay.scan_scout_records",
        "schedule": crontab(minute="*/5"),  # 每5分钟扫描一次
    },
    "scan-raid-runs": {
        "task": "gameplay.scan_raid_runs",
        "schedule": crontab(minute="*/5"),  # 每5分钟扫描一次
    },
    # 交易行过期挂单处理
    "process-expired-market-listings": {
        "task": "trade.process_expired_listings",
        "schedule": crontab(minute="*/2"),  # 每2分钟处理一次
    },
    # 数据清理任务
    "cleanup-old-resource-events": {
        "task": "gameplay.cleanup_old_data",
        "schedule": crontab(hour=4, minute=0),  # 每天04:00执行
    },
    # 拍卖行定时任务
    "settle-auction-round": {
        "task": "trade.settle_auction_round",
        "schedule": crontab(hour="0,12", minute=5),  # 每天0:05和12:05检查结算
    },
    "check-create-auction-round": {
        "task": "trade.create_auction_round",
        "schedule": crontab(hour=0, minute=10),  # 每天0:10检查创建新轮次
    },
}

ACCESS_LOG_ENABLED = env("DJANGO_ACCESS_LOG", "1") == "1"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "request_id": {
            "()": "core.middleware.RequestIDFilter",
        }
    },
    "formatters": {
        "verbose": {
            "format": "[%(request_id)s] %(levelname)s %(asctime)s %(name)s:%(lineno)s %(message)s",
        }
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
            "filters": ["request_id"],
        }
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
}


# ============================================================================
# SECURITY BASELINE CONFIGURATION
# ============================================================================
# Comprehensive security settings following Django security best practices
# and OWASP guidelines. These settings are production-ready and should not
# be disabled unless you have a specific reason and understand the risks.

# Session Security
# ----------------
# Ensure session cookies are only sent over HTTPS in production
SESSION_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_HTTPONLY = True  # Prevent JavaScript access to session cookie
SESSION_COOKIE_SAMESITE = "Lax"  # CSRF protection via SameSite

# CSRF Security
# -------------
# Ensure CSRF cookies are only sent over HTTPS in production
CSRF_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_HTTPONLY = True  # Prevent JavaScript access to CSRF token
CSRF_COOKIE_SAMESITE = "Lax"  # Additional CSRF protection

# Trusted origins for CSRF protection
# Add your production domains here, e.g., "https://example.com"
csrf_origins_str = env("DJANGO_CSRF_TRUSTED_ORIGINS", "")
CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in csrf_origins_str.split(",")
    if origin.strip()
]

# SSL/HTTPS Configuration
# -----------------------
# Redirect all HTTP requests to HTTPS in production
SECURE_SSL_REDIRECT = env("DJANGO_SECURE_SSL_REDIRECT", "1" if not DEBUG else "0") == "1"

# Trust X-Forwarded-Proto header from proxy (nginx, load balancer)
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# HTTP Strict Transport Security (HSTS)
# --------------------------------------
# Force browsers to use HTTPS for all future requests
# 31536000 seconds = 1 year
SECURE_HSTS_SECONDS = int(env("DJANGO_SECURE_HSTS_SECONDS", "31536000" if not DEBUG else "0"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = not DEBUG  # Apply HSTS to all subdomains
SECURE_HSTS_PRELOAD = not DEBUG  # Allow preloading in browsers' HSTS lists

# Content Security
# ----------------
SECURE_CONTENT_TYPE_NOSNIFF = True  # Prevent MIME type sniffing
SECURE_BROWSER_XSS_FILTER = True  # Enable browser's XSS filter
X_FRAME_OPTIONS = "DENY"  # Prevent clickjacking attacks

# File Upload Limits
# ------------------
# Prevent denial-of-service via large file uploads
# 10MB default limit
FILE_UPLOAD_MAX_MEMORY_SIZE = int(env("DJANGO_FILE_UPLOAD_MAX_MEMORY_SIZE", str(10 * 1024 * 1024)))
DATA_UPLOAD_MAX_MEMORY_SIZE = int(env("DJANGO_DATA_UPLOAD_MAX_MEMORY_SIZE", str(10 * 1024 * 1024)))

# Additional Security Headers
# ---------------------------
# Referrer Policy: Control referrer information sent to other sites
SECURE_REFERRER_POLICY = "same-origin"

# ============================================================================
# DEVELOPMENT ENVIRONMENT WARNINGS
# ============================================================================

# ============================================================================
# TEST ENVIRONMENT OVERRIDES
# ============================================================================
# When running tests (pytest/`manage.py test`) we default to lightweight local
# backends to avoid requiring external services (MySQL/Redis).
RUNNING_TESTS = ("pytest" in sys.modules) or ("test" in sys.argv)
if RUNNING_TESTS and env("DJANGO_TEST_USE_ENV_SERVICES", "0") != "1":
    # Celery's Settings object prioritizes CELERY_* environment variables over Django settings.
    # During tests we want to avoid any external broker/backend (Redis), so we clear these
    # env vars and rely on the in-memory settings below.
    for key in (
        "CELERY_BROKER_URL",
        "CELERY_RESULT_BACKEND",
        "CELERY_BROKER_READ_URL",
        "CELERY_BROKER_WRITE_URL",
    ):
        os.environ.pop(key, None)

    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": ":memory:",
        }
    }
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        }
    }
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels.layers.InMemoryChannelLayer",
        }
    }
    # Use in-memory broker/backend to avoid external Redis dependency during tests.
    # Do NOT enable eager mode here: some tasks reschedule themselves based on
    # countdown and would recurse infinitely when executed eagerly.
    CELERY_BROKER_URL = "memory://"
    CELERY_RESULT_BACKEND = "cache+memory://"
    CELERY_TASK_ALWAYS_EAGER = False
    try:
        from config.celery import app as celery_app

        celery_app.conf.update(
            broker_url=CELERY_BROKER_URL,
            result_backend=CELERY_RESULT_BACKEND,
            task_always_eager=CELERY_TASK_ALWAYS_EAGER,
        )
    except Exception:
        pass

if DEBUG:
    import warnings
    warnings.warn(
        "Running in DEBUG mode. Security features are relaxed. "
        "DO NOT use DEBUG=True in production!",
        RuntimeWarning
    )
