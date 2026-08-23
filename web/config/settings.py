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
    }
}

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
# Multi-user from the start of the team release: everything requires a
# login; accounts are created by the admin (see README). Saved
# portfolios belong to their creator; /p/<uuid> links are readable by
# any logged-in user.
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "/"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
