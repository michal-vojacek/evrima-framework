"""Short forms live in modal dialogs; a rejected one opens again.

A rejected form redirects back to its page like any other POST (so a refresh
never re-submits it). The page then reopens the same dialog with the submitted
values and the error. The state survives exactly one request in the session.

In a view:

    if errors:
        return modal.reopen("reference-form", t("…"), url_for(...))

In the template, the `modal()` macro reopens the dialog and `mv()` fills the
fields (evrima/admin/_macros.html).
"""

from collections.abc import Iterable
from typing import Any

from flask import g, has_request_context, redirect, request, session
from werkzeug.local import LocalProxy
from werkzeug.wrappers.response import Response

_SESSION_KEY = "evrima_modal"


def submitted(list_fields: Iterable[str] = ()) -> dict[str, Any]:
    """Return the submitted fields without the CSRF token.

    Fields named in `list_fields` (repeated inputs such as tags) are kept as
    lists; every other field keeps its first value.
    """
    lists = set(list_fields)
    values: dict[str, Any] = {}
    for key in request.form:
        if key == "csrf_token":
            continue
        all_values = request.form.getlist(key)
        values[key] = all_values if key in lists else all_values[0]
    return values


def reopen(
    modal_id: str,
    error: str,
    target: str,
    form: dict[str, Any] | None = None,
    list_fields: Iterable[str] = (),
) -> Response:
    """Remember the dialog, its error and values, and redirect to `target`."""
    session[_SESSION_KEY] = {
        "id": modal_id,
        "error": error,
        "form": submitted(list_fields) if form is None else form,
    }
    return redirect(target)


def _state() -> dict[str, Any]:
    """Take the state from the session once per request; every template can ask."""
    if not has_request_context():
        return {}
    if "evrima_modal" not in g:
        g.evrima_modal = session.pop(_SESSION_KEY, None) or {}
    return g.evrima_modal


state = LocalProxy(_state)
