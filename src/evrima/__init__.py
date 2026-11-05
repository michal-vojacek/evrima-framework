"""Evrima: lightweight, security-first Flask framework and CMS for simple websites.

The public entry point is `create_app`; see evrima.app.
"""

from evrima.app import create_app
from evrima.config import ConfigError
from evrima.version import get_version

__all__ = ["ConfigError", "create_app", "get_version"]
