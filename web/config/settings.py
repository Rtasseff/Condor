"""Django settings — Condor Funds v2.

Local development works with no environment set (safe defaults, DEBUG
on). Production (docs/DEPLOY.md) is configured entirely by CONDOR_*
environment variables — no separate settings file to drift.
"""

import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent  # web/
REPO_ROOT = BASE_DIR.parent  # condor_v2/

# make the condor analytics package importable
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# --- environment (production sets these; dev defaults are safe) -----
SECRET_KEY = os.environ.get(
    "CONDOR_SECRET_KEY", "django-insecure-condor-v2-local-prototype-only")
DEBUG = os.environ.get("CONDOR_DEBUG", "1") == "1"
ALLOWED_HOSTS = os.environ.get(
    "CONDOR_ALLOWED_HOSTS", "127.0.0.1,localhost").split(",")
# e.g. CONDOR_CSRF_ORIGINS=https://condor.example.com
CSRF_TRUSTED_ORIGINS = [o for o in os.environ.get(
    "CONDOR_CSRF_ORIGINS", "").split(",") if o]

INSTALLED_APPS = [
    "django.contrib.admin",           # user management for the small team
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "explorer",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",   # static files w/o nginx
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
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "explorer.context.contribution_reminder",
                "explorer.context.signups_enabled",
            ]
        },
    }
]

WSGI_APPLICATION = "config.wsgi.application"

# Saved portfolios + accounts live here. Local file, never committed;
# in production point CONDOR_DB_PATH at the persistent volume.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.environ.get("CONDOR_DB_PATH", BASE_DIR / "db.sqlite3"),
        # WAL + a patient timeout: cheap insurance under multiple
        # gunicorn workers (and harmless in dev)
        "OPTIONS": {
            "timeout": 20,
            "init_command": "PRAGMA journal_mode=WAL;"
                            " PRAGMA synchronous=NORMAL;",
        },
    }
}

# --- rate limiting (django-ratelimit) --------------------------------
# Explore is public (anonymous visitors can analyze and forecast), so the
# compute endpoints need a per-IP cap. Counters live in this cache.
#
# Known softness: LocMem is per-process and the Dockerfile runs 2 gunicorn
# workers, so a visitor whose requests land on both workers gets roughly
# 2x the nominal rate. That is fine for v1 abuse protection — the point is
# to stop a script, not to meter honest use. A shared cache (Redis, or
# Fly's) is the upgrade when there is a reason for one.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "condor-ratelimit",
        # LocMem defaults to 300 entries and culls a third of them at
        # random when full. A counter is one entry per (endpoint, IP,
        # window), so a burst of traffic from many addresses would evict
        # live counters and quietly hand people a fresh allowance. Room
        # for a few thousand costs nothing on a box this size.
        "OPTIONS": {"MAX_ENTRIES": 10000},
    }
}

# Per-IP limits, by name (explorer.throttle). Overridable in tests.
CONDOR_RATE_LIMITS = {
    "analyze": "15/m",
    "forecast": "15/m",
    "asset": "60/m",
    "login": "10/m",
    "signup": "5/h",
    "reset": "5/h",
}

# One shared LocMem counter would leak between tests — the suite is one
# process making hundreds of requests from one IP. The rate-limit tests
# turn it back on explicitly with override_settings.
_TESTING = "test" in sys.argv
RATELIMIT_ENABLE = os.environ.get(
    "CONDOR_RATELIMIT", "0" if _TESTING else "1") == "1"

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"          # collectstatic target
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}

TIME_ZONE = "UTC"   # explicit: 4 users in 4 time zones, one server clock
USE_TZ = True

# --- production hardening (no-ops while DEBUG) ----------------------
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_HSTS_SECONDS = 3600      # modest on purpose; raise post-0.1
    X_FRAME_OPTIONS = "DENY"

# ---- accounts -------------------------------------------------------
# Multi-user from the start of the team release; accounts are created by
# the admin (see README). Explore (Build/Optimize/Forecast) and /learn are
# public — a stranger can play with pretend money before signing up, and
# their draft lives in their own browser. Everything that reads or writes
# a *user's* data still requires a login: the draft API, saved portfolios,
# and everything under My portfolio. Saved portfolios belong to their
# creator; a /p/<uuid> link is a capability, readable by anyone holding it.
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "/"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# ---- email / self-serve accounts -----------------------------------
# The sender is RT's Gmail via an app password — to this codebase that is
# nothing but SMTP settings read from the environment. Locally and in
# tests, where these are unset, mail goes to the console instead of
# nowhere, so the flow stays exercisable without Gmail creds.
CONDOR_EMAIL_USER = os.environ.get("CONDOR_EMAIL_USER")
CONDOR_EMAIL_PASSWORD = os.environ.get("CONDOR_EMAIL_PASSWORD")
_EMAIL_CONFIGURED = bool(CONDOR_EMAIL_USER and CONDOR_EMAIL_PASSWORD)

if _EMAIL_CONFIGURED:
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    EMAIL_HOST = "smtp.gmail.com"
    EMAIL_PORT = 587
    EMAIL_USE_TLS = True
    EMAIL_HOST_USER = CONDOR_EMAIL_USER
    EMAIL_HOST_PASSWORD = CONDOR_EMAIL_PASSWORD
    EMAIL_TIMEOUT = 10  # a hung SMTP conversation must not hang a request worker
    DEFAULT_FROM_EMAIL = f"Condor Funds <{CONDOR_EMAIL_USER}>"
else:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# Self-serve signup needs a real mailbox to send activation links from;
# without one, minting an inactive account whose link goes to a log file
# would just strand people. DEBUG (dev/tests) always allows it so the
# flow is exercisable locally without Gmail creds.
SIGNUPS_ENABLED = _EMAIL_CONFIGURED or DEBUG

# Governs both password-reset AND account-activation links — both are
# built on Django's default_token_generator, which reads this one setting.
PASSWORD_RESET_TIMEOUT = 3 * 24 * 3600  # 3 days

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
