"""Audit log: who changed what and when (docs/framework.md, "Security baseline").

The IP address is kept with each entry: when an account has been taken over,
the log shows from where and since when (the moment to restore a backup from).
"""

from flask import has_request_context, request

from evrima.auth.models import Administrator, AuditEntry
from evrima.db import db


def record(action: str, *, admin: Administrator | None = None, email: str = "", detail: str = "") -> None:
    """Write one entry and commit it.

    `action` is a short machine-readable name such as "login" or
    "password.changed"; `detail` is free text for people.
    """
    db.session.add(AuditEntry(
        administrator_id=admin.id if admin else None,
        email=(admin.email if admin else email)[:254],
        action=action[:60],
        detail=detail,
        ip=(request.remote_addr or "")[:45] if has_request_context() else "",
    ))
    db.session.commit()
