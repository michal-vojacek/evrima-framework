"""Where the admin sends people after an action (login, language switch)."""

from urllib.parse import urlsplit

from flask import url_for


def safe_next(target: str | None) -> str:
    """Return `target` if it is a path on this website, else the admin start page.

    Only local paths are accepted: a crafted link or form must not turn the
    login or the language switch into a redirect to another website.
    """
    if target and target.startswith("/") and not target.startswith("//") and "\\" not in target:
        parts = urlsplit(target)
        if not parts.scheme and not parts.netloc:
            return target
    return url_for("evrima_admin.index")
