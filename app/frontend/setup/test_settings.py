"""Configuração exclusiva para testes locais; nunca usar no Render."""

import os

os.environ.update({
    "DJANGO_SECRET_KEY": "test-only-not-for-production-8f4c0b519afc590d",
    "DJANGO_DEBUG": "false",
    "DJANGO_ALLOWED_HOSTS": "testserver,localhost",
    "DJANGO_CSRF_TRUSTED_ORIGINS": "",
    "DATABASE_URL": "postgresql://test:test@localhost/test?sslmode=require",
    "FASTAPI_BASE_URL": "https://api.example.test/api",
    "FASTAPI_TIMEOUT": "30",
})

from .settings import *  # noqa: E402,F403

DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
