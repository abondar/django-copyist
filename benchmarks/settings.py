"""
Settings for the benchmark. SQLite by default, PostgreSQL if POSTGRES_HOST is set.
"""

import os
import tempfile
from pathlib import Path

SECRET_KEY = "benchmark"
DEBUG = False
USE_TZ = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
INSTALLED_APPS = ["django.contrib.contenttypes", "benchmarks"]

if os.environ.get("POSTGRES_HOST"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "HOST": os.environ["POSTGRES_HOST"],
            "PORT": os.environ.get("POSTGRES_PORT", "5432"),
            "USER": os.environ.get("POSTGRES_USER", "postgres"),
            "PASSWORD": os.environ.get("POSTGRES_PASSWORD", "postgres"),
            "NAME": "copyist_bench",
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": str(Path(tempfile.gettempdir()) / "copyist_bench.sqlite3"),
            # An on-disk file: an in-memory database hides I/O costs.
            "TEST": {"NAME": str(Path(tempfile.gettempdir()) / "test_copyist_bench.sqlite3")},
        }
    }
