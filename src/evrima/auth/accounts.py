"""Pages behind the login: the user's own account and the administrators.

Short forms (profile, password, inviting) open in dialogs and reopen with the
error after a rejected submit (evrima/admin/modal.py).

There is a single role: every administrator may invite, edit and remove
others (docs/framework.md, "Admin login"). Nobody removes themselves or
changes their own e-mail; another administrator or `flask evrima
set-admin-email` does that.
"""

from flask import Blueprint, flash, redirect, render_template, request, url_for
from sqlalchemy import select, update

from evrima import i18n
from evrima.admin import modal
from evrima.auth import audit, credentials, emails, protect, sessions
from evrima.auth.models import AccountLink, Administrator
from evrima.auth.views import (EMAIL_PATTERN, INVITE_LIFETIME, RESET_LIFETIME, create_link,
                               normalise_email)
from evrima.db import db, utcnow
from evrima.i18n import LANGUAGES
from evrima.i18n import translate as t
from evrima.mail import MailError

bp = Blueprint("evrima_account", __name__, url_prefix="/admin")
protect(bp)


def _me() -> Administrator:
    """The logged-in administrator (guaranteed by `protect`)."""
    return sessions.current_admin()


# --- My account ---------------------------------------------------------------------

@bp.get("/account")
def account():
    """Profile and password."""
    return render_template("evrima/admin/account/account.html", me=_me())


@bp.post("/account/profile")
def save_profile():
    """Name and language."""
    me = _me()
    language = request.form.get("language", me.language)
    if language not in LANGUAGES:
        language = me.language
    me.name = request.form.get("name", "").strip()[:120]
    me.language = language
    db.session.commit()
    i18n.set_language(language)
    flash(t("auth.account.profile_saved"), "success")
    return redirect(url_for("evrima_account.account"))


@bp.post("/account/password")
def change_password():
    """A new password ends every other session."""
    me = _me()
    back = url_for("evrima_account.account")
    if not credentials.verify_password(me.password_hash, request.form.get("current", "")):
        return modal.reopen("password-form", t("auth.password.wrong_current"), back, form={})
    password = request.form.get("password", "")
    problem = credentials.password_problem(password)
    if problem:
        return modal.reopen("password-form", t(problem), back, form={})
    if password != request.form.get("confirm", ""):
        return modal.reopen("password-form", t("auth.password.mismatch"), back, form={})

    me.password_hash = credentials.hash_password(password)
    me.password_changed_at = utcnow()
    db.session.commit()
    audit.record("password.changed", admin=me)
    return _restart_session(me, t("auth.account.password_saved"))


@bp.post("/account/logout-everywhere")
def logout_everywhere():
    """End every other session."""
    me = _me()
    audit.record("sessions.ended", admin=me)
    return _restart_session(me, t("auth.account.logged_out_everywhere"))


def _restart_session(me: Administrator, message: str, target: str | None = None):
    """End all sessions of `me`, then log this browser in again so the user stays."""
    sessions.end_all(me)
    flash(message, "success")
    response = redirect(target or url_for("evrima_account.account"))
    sessions.start_session(response, me)
    return response


# --- Administrators -----------------------------------------------------------------

@bp.get("/administrators")
def administrators():
    """Everyone who can log in, invited people included."""
    people = db.session.scalars(select(Administrator).order_by(Administrator.email)).all()
    return render_template("evrima/admin/account/administrators.html", people=people, me=_me())


@bp.post("/administrators/invite")
def invite():
    """Create an account without a password and e-mail a link to choose one."""
    back = url_for("evrima_account.administrators")
    email = normalise_email(request.form.get("email"))
    language = request.form.get("language", "cs")
    if not EMAIL_PATTERN.match(email):
        return modal.reopen("invite-form", t("auth.admins.invalid_email"), back)
    if db.session.scalar(select(Administrator).where(Administrator.email == email)):
        return modal.reopen("invite-form", t("auth.admins.exists"), back)

    person = Administrator(
        email=email, name=request.form.get("name", "").strip()[:120],
        language=language if language in LANGUAGES else "cs")
    db.session.add(person)
    db.session.commit()
    audit.record("admin.invited", admin=_me(), detail=email)
    _send_invitation(person)
    return redirect(back)


@bp.post("/administrators/<int:person_id>/resend")
def resend_invite(person_id: int):
    """Send a fresh invitation; the previous link stops working."""
    person = db.session.get(Administrator, person_id)
    if person is not None and person.is_invited:
        _send_invitation(person)
    return redirect(url_for("evrima_account.administrators"))


def _send_invitation(person: Administrator) -> None:
    """Create the invitation link and e-mail it, reporting the outcome."""
    token = create_link(person, "invite", INVITE_LIFETIME)
    try:
        emails.send_invite(person, token, invited_by=_me())
        flash(t("auth.admins.invite_sent", email=person.email), "success")
    except MailError:
        flash(t("auth.admins.invite_failed"), "danger")


@bp.post("/administrators/<int:person_id>/edit")
def edit(person_id: int):
    """Name, language, e-mail and optionally a new password of an administrator.

    The own e-mail cannot be changed here (another administrator does it),
    and neither can the own password: the account page asks for the current
    one, so that a browser left logged in cannot be used to take the account
    over for good. A changed e-mail or a new password ends the person's sessions; a changed
    e-mail also cancels their unused links, which went to the old address.
    """
    me = _me()
    person = db.session.get(Administrator, person_id)
    back = url_for("evrima_account.administrators")
    if person is None:
        return redirect(back)
    dialog = f"edit-{person.id}"
    keep_values = {key: request.form.get(key, "") for key in ("name", "email", "language")}

    email = normalise_email(request.form.get("email")) if person.id != me.id else person.email
    if not EMAIL_PATTERN.match(email):
        return modal.reopen(dialog, t("auth.admins.invalid_email"), back, form=keep_values)
    if email != person.email and db.session.scalar(select(Administrator).where(Administrator.email == email)):
        return modal.reopen(dialog, t("auth.admins.exists"), back, form=keep_values)
    password = request.form.get("password", "") if person.id != me.id else ""
    if password:
        problem = credentials.password_problem(password)
        if problem:
            return modal.reopen(dialog, t(problem), back, form=keep_values)
        if password != request.form.get("confirm", ""):
            return modal.reopen(dialog, t("auth.password.mismatch"), back, form=keep_values)

    language = request.form.get("language", person.language)
    person.name = request.form.get("name", "").strip()[:120]
    person.language = language if language in LANGUAGES else person.language
    email_changed = email != person.email
    old_email = person.email
    person.email = email
    if password:
        person.password_hash = credentials.hash_password(password)
        person.password_changed_at = utcnow()
    db.session.commit()

    if email_changed or password:
        # Links sent earlier went to the old address, or would replace the
        # password just set: neither should keep working.
        cancel_links(person)
    if email_changed:
        audit.record("admin.email_changed", admin=me, detail=f"{old_email} -> {email}")
    if password:
        audit.record("password.set_by_admin", admin=me, detail=person.email)
    audit.record("admin.edited", admin=me, detail=person.email)
    if email_changed or password:
        # Ending the sessions of the person editing themselves would log them
        # out mid-edit; they keep this browser, like after their own password change.
        if person.id == me.id:
            return _restart_session(me, t("auth.admins.saved", email=person.email), back)
        sessions.end_all(person)
    flash(t("auth.admins.saved", email=person.email), "success")
    if email_changed and person.is_invited:
        _send_invitation(person)
    return redirect(back)


@bp.post("/administrators/<int:person_id>/reset")
def send_reset(person_id: int):
    """E-mail the administrator a link to set a new password themselves."""
    person = db.session.get(Administrator, person_id)
    if person is not None and not person.is_invited:
        token = create_link(person, "reset", RESET_LIFETIME)
        audit.record("password.reset_sent", admin=_me(), detail=person.email)
        try:
            emails.send_reset(person, token)
            flash(t("auth.admins.reset_sent", email=person.email), "success")
        except MailError:
            flash(t("auth.admins.reset_failed"), "danger")
    return redirect(url_for("evrima_account.administrators"))


def cancel_links(person: Administrator) -> None:
    """Invalidate the person's unused reset and invitation links."""
    db.session.execute(
        update(AccountLink)
        .where(AccountLink.administrator_id == person.id, AccountLink.used_at.is_(None))
        .values(used_at=utcnow()))
    db.session.commit()


@bp.post("/administrators/<int:person_id>/remove")
def remove(person_id: int):
    """Remove an administrator. Nobody can remove themselves, so one always remains."""
    me = _me()
    person = db.session.get(Administrator, person_id)
    if person is None:
        return redirect(url_for("evrima_account.administrators"))
    if person.id == me.id:
        flash(t("auth.admins.cannot_remove_self"), "danger")
        return redirect(url_for("evrima_account.administrators"))
    email = person.email
    db.session.delete(person)
    db.session.commit()
    audit.record("admin.removed", admin=me, detail=email)
    flash(t("auth.admins.removed", email=email), "success")
    return redirect(url_for("evrima_account.administrators"))
