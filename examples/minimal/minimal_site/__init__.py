"""Minimal example website built on Evrima.

`flask --app minimal_site run` finds the `create_app` factory below on its own.
"""

import evrima
from minimal_site.modules import references

from minimal_site.pages import pages


def create_app(config_overrides=None):
    """Build the website: Evrima's core, the references module and this website's pages."""
    return evrima.create_app(
        __name__, blueprints=[pages], modules=[references], config_overrides=config_overrides)
