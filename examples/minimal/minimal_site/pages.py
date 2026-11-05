"""Routes of the minimal example website."""

from flask import Blueprint, render_template

from minimal_site.modules import references

pages = Blueprint("pages", __name__)


@pages.get("/")
def home():
    """The home page."""
    return render_template("home.html")


@pages.get("/references")
def reference_list():
    """Published references, in the order set in the admin."""
    return render_template("references.html", items=references.published())
