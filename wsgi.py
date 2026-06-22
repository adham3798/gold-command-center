# -*- coding: utf-8 -*-
"""
Gunicorn entrypoint. Imports the existing app, then attaches the Scalp tab's
/api/scalp endpoint. Run via:  gunicorn wsgi:app
Keeps app.py untouched.
"""
from app import app   # the existing Flask instance (app.py)
import scalp_api       # registers /api/scalp on it (side-effect import)

# expose for gunicorn
__all__ = ["app"]
