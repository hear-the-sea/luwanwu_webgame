"""
Base Django settings - core configuration.
"""

from __future__ import annotations

import math
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent.parent

load_dotenv(BASE_DIR / ".env")


def env(key: str, default: str = "") -> str:
    return os.getenv(key, default)


# Game time multiplier
try:
    GAME_TIME_MULTIPLIER = float(env("GAME_TIME_MULTIPLIER", "1") or "1")
except (TypeError, ValueError):
    GAME_TIME_MULTIPLIER = 1.0
if not math.isfinite(GAME_TIME_MULTIPLIER) or GAME_TIME_MULTIPLIER <= 0:
    GAME_TIME_MULTIPLIER = 1.0

# DEBUG should default to False for security
DEBUG = env("DJANGO_DEBUG", "0") == "1"

# Battle debugger is a development-only tool and should be explicitly enabled.
ENABLE_BATTLE_DEBUGGER = DEBUG and env("DJANGO_ENABLE_DEBUGGER", "0") == "1"

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "drf_spectacular",
    "corsheaders",
    "channels",
    "accounts",
    "gameplay",
    "guests",
    "battle",
    "trade",
    "guilds",
    "battle_debugger" if ENABLE_BATTLE_DEBUGGER else None,
]
INSTALLED_APPS = [app for app in INSTALLED_APPS if app]

MIDDLEWARE = [
    "core.middleware.RequestIDMiddleware",
    "core.middleware.AccessLogMiddleware",
    "corsheaders.middleware.CorsMiddleware",
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
    ],
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": "100/hour",
        "user": "1000/hour",
        "recruit": "20/hour",
        "battle": "100/hour",
        "claim": "50/hour",
    },
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "春秋乱世庄园主 API",
    "DESCRIPTION": "Django 游戏项目 API 文档",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "SCHEMA_PATH_PREFIX": r"/api/",
}

# Trusted reverse proxy addresses (exact IPs or CIDR), comma-separated.
trusted_proxy_ips_str = env("DJANGO_TRUSTED_PROXY_IPS", "")
TRUSTED_PROXY_IPS = [ip.strip() for ip in trusted_proxy_ips_str.split(",") if ip.strip()]

ACCESS_LOG_ENABLED = env("DJANGO_ACCESS_LOG", "1") == "1"
ACCESS_LOG_TRUST_PROXY = env("DJANGO_ACCESS_LOG_TRUST_PROXY", "0") == "1"
if ACCESS_LOG_TRUST_PROXY and not TRUSTED_PROXY_IPS:
    ACCESS_LOG_TRUST_PROXY = False

# Minimum intervals for resource sync and manor state refresh
RESOURCE_SYNC_MIN_INTERVAL_SECONDS = int(env("DJANGO_RESOURCE_SYNC_MIN_INTERVAL_SECONDS", "1" if DEBUG else "5"))
MANOR_STATE_REFRESH_MIN_INTERVAL_SECONDS = int(
    env("DJANGO_MANOR_STATE_REFRESH_MIN_INTERVAL_SECONDS", "1" if DEBUG else "5")
)

# Cache TTL for home/dashboard stats
HOME_STATS_CACHE_TTL_SECONDS = int(env("DJANGO_HOME_STATS_CACHE_TTL_SECONDS", "15"))
# Cache TTL for defender 24h raid-received counter in attack checks
RAID_RECENT_ATTACKS_CACHE_TTL_SECONDS = int(env("DJANGO_RAID_RECENT_ATTACKS_CACHE_TTL_SECONDS", "5"))

# High-value thresholds for logging/monitoring
TRADE_HIGH_VALUE_SILVER_THRESHOLD = int(env("DJANGO_TRADE_HIGH_VALUE_SILVER_THRESHOLD", "1000000"))
AUCTION_HIGH_BID_THRESHOLD = int(env("DJANGO_AUCTION_HIGH_BID_THRESHOLD", "200"))

# Detect test runs
RUNNING_TESTS = ("pytest" in sys.modules) or ("test" in sys.argv) or ("pytest" in os.path.basename(sys.argv[0] or ""))
