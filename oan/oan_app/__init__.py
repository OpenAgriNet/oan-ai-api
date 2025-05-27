# path: oan/oan_app/__init__.py

from __future__ import absolute_import, unicode_literals
from .celery import app as celery_app
from dotenv import load_dotenv

load_dotenv(override=True)


__all__ = ('celery_app',)