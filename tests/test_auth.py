"""Admin login: password, PIN, trusted devices, lockout, sessions, reset, TOTP, administrators."""

import re
from datetime import timedelta

import pyotp
import pytest
from sqlalchemy import select

from conftest import (ADMIN_EMAIL, ADMIN_PASSWORD, add_admin, csrf_token, https_client,
                      last_pin, log_in)
from evrima import mail
from evrima.auth import totp
from evrima.auth.models import AdminSession, Administrator, AuditEntry, LoginChallenge
from evrima.db import db, utcnow

NEW_PASSWORD = "a brand new long password"


def admin(app, email=ADMIN_EMAIL):
    """Load an administrator fresh from the database."""
    with app.app_context():
        return db.session.scalar(select(Administrator).where(Administrator.email == email))


def outbox(app):
    """The messages sent so far."""
    with app.app_context():
        return list(mail.outbox())


def cookie(response, name):
    """The Set-Cookie header for `name`."""
    return next(h for h in response.headers.getlist("Set-Cookie") if h.startswith(name + "="))


def audit_actions(app):
    """The actions in the audit log, oldest first."""
    with app.app_context():
        return [e.action for e in db.session.scalars(select(AuditEntry).order_by(AuditEntry.id))]


@pytest.fixture
def account(app):
    """The test administrator, not logged in."""
    add_admin(app)
    return https_client(app)


# --- Password step ----------------------------------------------------------------------

def test_wrong_password_is_refused_without_revealing_accounts(app, account):
    token = csrf_token(account)
    wrong = account.post("/admin/login", data={"csrf_token": token, "email": ADMIN_EMAIL, "password": "nope nope nope"})
    unknown = account.post("/admin/login", data={"csrf_token": token, "email": "nobody@example.com", "password": "nope nope nope"})
    for response in (wrong, unknown):
        assert response.status_code == 200
        assert "Nesprávný e-mail nebo heslo." in response.get_data(as_text=True)
        assert "evrima_admin=" not in str(response.headers)
    assert audit_actions(app).count("login.failed") == 2


def test_full_login_sets_strict_cookies(app, account):
    response = log_in(app, account)
    assert response.status_code == 302
    session_cookie = cookie(response, "evrima_admin")
    device_cookie = cookie(response, "evrima_device")
    for header in (session_cookie, device_cookie):
        assert "HttpOnly" in header and "Secure" in header and "Path=/admin" in header
    assert "SameSite=Lax" in session_cookie
    assert "SameSite=Strict" in device_cookie
    assert account.get("/admin/").status_code == 200
    assert "login" in audit_actions(app)


def test_pin_email_carries_the_warning_and_no_pin_in_subject(app, account):
    token = csrf_token(account)
    account.post("/admin/login", data={"csrf_token": token, "email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    message = outbox(app)[-1]
    pin = last_pin(app)
    assert pin not in message["Subject"]
    body = message.get_content()
    assert "někdo zná vaše heslo" in body
    assert "/admin/password/forgot" in body


def test_trusted_device_skips_the_pin(app, account):
    log_in(app, account)
    token = csrf_token(account, "/admin/")
    account.post("/admin/logout", data={"csrf_token": token})
    sent = len(outbox(app))
    response = account.post("/admin/login", data={
        "csrf_token": csrf_token(account), "email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert response.headers["Location"] == "/admin/"
    assert len(outbox(app)) == sent          # no new PIN e-mail


def test_login_returns_to_the_requested_page(app, account):
    assert "next=/admin/account" in account.get("/admin/account").headers["Location"]
    token = csrf_token(account)
    account.post("/admin/login", data={
        "csrf_token": token, "email": ADMIN_EMAIL, "password": ADMIN_PASSWORD, "next": "/admin/account"})
    response = account.post("/admin/login/verify", data={"csrf_token": token, "method": "pin", "code": last_pin(app)})
    assert response.headers["Location"] == "/admin/account"


# --- Lockout --------------------------------------------------------------------------

def test_lockout_after_ten_failures_per_email_and_ip(app, account):
    token = csrf_token(account)
    for _ in range(10):
        account.post("/admin/login", data={"csrf_token": token, "email": ADMIN_EMAIL, "password": "wrong password!"})
    locked = account.post("/admin/login", data={"csrf_token": token, "email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert locked.status_code == 429
    assert "Příliš mnoho neúspěšných pokusů" in locked.get_data(as_text=True)

    # The real owner on another network is not locked out by the attacker.
    owner = https_client(app)
    owner.environ_base["REMOTE_ADDR"] = "203.0.113.9"
    assert log_in(app, owner).status_code == 302


# --- PIN step ---------------------------------------------------------------------------

def start_login(app, client):
    """Submit the password and return the CSRF token for the next step."""
    token = csrf_token(client)
    client.post("/admin/login", data={"csrf_token": token, "email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    return token


def test_five_wrong_pins_burn_the_challenge(app, account):
    token = start_login(app, account)
    pin = last_pin(app)
    wrong = "000000" if pin != "000000" else "111111"
    for _ in range(5):
        account.post("/admin/login/verify", data={"csrf_token": token, "method": "pin", "code": wrong})
    response = account.post("/admin/login/verify", data={"csrf_token": token, "method": "pin", "code": pin})
    assert response.status_code == 200
    assert "Příliš mnoho chybných kódů" in response.get_data(as_text=True)


def test_expired_pin_is_refused(app, account):
    token = start_login(app, account)
    with app.app_context():
        challenge = db.session.scalars(select(LoginChallenge)).one()
        challenge.expires_at = utcnow() - timedelta(seconds=1)
        db.session.commit()
    response = account.post("/admin/login/verify", data={"csrf_token": token, "method": "pin", "code": last_pin(app)})
    assert response.status_code == 302 and response.headers["Location"].endswith("/admin/login")
    assert "evrima_admin=" not in str(response.headers)
    # An expired pending login cannot ask for new codes either.
    resend = account.post("/admin/login/resend", data={"csrf_token": token})
    assert resend.headers["Location"].endswith("/admin/login")
    assert len(outbox(app)) == 1


def test_password_change_cancels_a_pending_login(app, account):
    """A browser that knew the old password cannot finish the login after a reset."""
    from evrima.auth import sessions

    token = start_login(app, account)
    pin = last_pin(app)
    with app.app_context():
        sessions.end_all(admin(app))
    response = account.post("/admin/login/verify", data={"csrf_token": token, "method": "pin", "code": pin})
    assert response.headers["Location"].endswith("/admin/login")
    assert "evrima_admin=" not in str(response.headers)


def test_wrong_totp_codes_burn_the_challenge(app):
    """TOTP guesses are counted per pending login, not only per IP address."""
    secret = pyotp.random_base32()
    with app.app_context():
        stored = totp.encrypt(secret)
    add_admin(app, totp_secret=stored)
    browser = https_client(app)
    token = start_login(app, browser)
    good = pyotp.TOTP(secret).now()
    wrong = "000000" if good != "000000" else "111111"
    for _ in range(5):
        browser.post("/admin/login/verify", data={"csrf_token": token, "method": "totp", "code": wrong})
    response = browser.post("/admin/login/verify", data={"csrf_token": token, "method": "totp", "code": good})
    assert response.status_code == 200
    assert "Příliš mnoho chybných kódů" in response.get_data(as_text=True)
    assert audit_actions(app).count("login.totp_failed") == 5


def test_codes_per_hour_are_limited(app, account):
    """Asking for new codes cannot hand out fresh attempts without end."""
    token = start_login(app, account)
    for _ in range(4):
        account.post("/admin/login/resend", data={"csrf_token": token})
    assert len(outbox(app)) == 5
    refused = account.post("/admin/login/resend", data={"csrf_token": token}, follow_redirects=True)
    assert "příliš mnoho kódů" in refused.get_data(as_text=True)
    assert len(outbox(app)) == 5
    assert "login.too_many_codes" in audit_actions(app)


def test_resend_replaces_the_pin(app, account):
    token = start_login(app, account)
    first = last_pin(app)
    account.post("/admin/login/resend", data={"csrf_token": token})
    second = last_pin(app)
    if first != second:
        refused = account.post("/admin/login/verify", data={"csrf_token": token, "method": "pin", "code": first})
        assert refused.status_code == 200
    accepted = account.post("/admin/login/verify", data={"csrf_token": token, "method": "pin", "code": second})
    assert accepted.status_code == 302


# --- Sessions -----------------------------------------------------------------------------

@pytest.mark.parametrize("field, age", [("last_seen_at", timedelta(hours=2, minutes=1)),
                                        ("created_at", timedelta(hours=24, minutes=1))])
def test_session_expires_after_idle_time_and_maximum_age(app, admin_client, field, age):
    with app.app_context():
        session = db.session.scalars(select(AdminSession)).one()
        setattr(session, field, utcnow() - age)
        db.session.commit()
    assert admin_client.get("/admin/").status_code == 302


def test_logout_ends_the_session(app, admin_client):
    response = admin_client.post("/admin/logout", data={"csrf_token": csrf_token(admin_client, "/admin/")})
    assert response.headers["Location"] == "/admin/login"
    assert admin_client.get("/admin/").status_code == 302
    with app.app_context():
        assert db.session.scalars(select(AdminSession)).all() == []


# --- Password change and reset ------------------------------------------------------------

def test_password_change_logs_out_other_devices(app, admin_client):
    other = https_client(app)
    other.environ_base["REMOTE_ADDR"] = "198.51.100.4"
    log_in(app, other)
    token = csrf_token(admin_client, "/admin/account")

    wrong = admin_client.post("/admin/account/password", data={
        "csrf_token": token, "current": "not it at all", "password": NEW_PASSWORD, "confirm": NEW_PASSWORD})
    assert "Současné heslo není správné." in admin_client.get(wrong.headers["Location"]).get_data(as_text=True)

    admin_client.post("/admin/account/password", data={
        "csrf_token": token, "current": ADMIN_PASSWORD, "password": NEW_PASSWORD, "confirm": NEW_PASSWORD})
    assert admin_client.get("/admin/account").status_code == 200    # this browser stays
    assert other.get("/admin/").status_code == 302                    # the other one is out
    assert "password.changed" in audit_actions(app)


def test_short_password_is_refused(app, admin_client):
    token = csrf_token(admin_client, "/admin/account")
    response = admin_client.post("/admin/account/password", data={
        "csrf_token": token, "current": ADMIN_PASSWORD, "password": "too short", "confirm": "too short"})
    page = admin_client.get(response.headers["Location"]).get_data(as_text=True)
    assert "Heslo musí mít aspoň 12 znaků." in page
    assert "too short" not in page          # passwords are never echoed back


def reset_link(app):
    """The set-password path from the last e-mail."""
    body = outbox(app)[-1].get_content()
    return re.search(r"https?://[^/\s]+(/admin/password/set/\S+)", body).group(1)


def test_forgotten_password_flow(app, account):
    token = csrf_token(account)
    unknown = account.post("/admin/password/forgot", data={"csrf_token": token, "email": "nobody@example.com"})
    known = account.post("/admin/password/forgot", data={"csrf_token": token, "email": ADMIN_EMAIL})
    assert unknown.headers["Location"] == known.headers["Location"]
    assert len(outbox(app)) == 1

    path = reset_link(app)
    account.post(path, data={"csrf_token": token, "password": NEW_PASSWORD, "confirm": NEW_PASSWORD})
    assert log_in(app, https_client(app), password=ADMIN_PASSWORD).status_code == 200      # old one fails
    assert log_in(app, https_client(app), password=NEW_PASSWORD).status_code == 302
    reused = account.get(path)
    assert reused.headers["Location"] == "/admin/login"                                    # one use only


# --- Administrators -------------------------------------------------------------------------

def test_invite_and_accept(app, admin_client):
    token = csrf_token(admin_client, "/admin/administrators")
    admin_client.post("/admin/administrators/invite", data={
        "csrf_token": token, "email": "Nova@Example.com", "name": "Nová Kolegyně", "language": "en"})
    invited = admin(app, "nova@example.com")
    assert invited.is_invited and invited.language == "en"
    assert outbox(app)[-1]["Subject"].startswith("Invitation")

    newcomer = https_client(app)
    path = reset_link(app)
    newcomer.post(path, data={"csrf_token": csrf_token(newcomer), "password": NEW_PASSWORD, "confirm": NEW_PASSWORD})
    assert log_in(app, newcomer, email="nova@example.com", password=NEW_PASSWORD).status_code == 302
    assert "invite.accepted" in audit_actions(app)


def test_invite_rejects_duplicates(app, admin_client):
    token = csrf_token(admin_client, "/admin/administrators")
    response = admin_client.post("/admin/administrators/invite", data={"csrf_token": token, "email": ADMIN_EMAIL})
    page = admin_client.get(response.headers["Location"]).get_data(as_text=True)
    assert "Tento e-mail už patří administrátorovi." in page


def test_remove_others_but_not_yourself(app, admin_client):
    me = admin(app)
    other_id = add_admin(app, email="other@example.com")
    token = csrf_token(admin_client, "/admin/administrators")
    admin_client.post(f"/admin/administrators/{me.id}/remove", data={"csrf_token": token})
    assert admin(app) is not None
    admin_client.post(f"/admin/administrators/{other_id}/remove", data={"csrf_token": token})
    assert admin(app, "other@example.com") is None


# --- TOTP ---------------------------------------------------------------------------------------

def test_totp_setup_and_login_with_code(app, admin_client):
    admin_client.get("/admin/account/totp")
    with app.app_context():
        secret = totp.decrypt(admin(app).totp_pending_secret)
    token = csrf_token(admin_client, "/admin/account/totp")
    refused = admin_client.post("/admin/account/totp", data={
        "csrf_token": token, "code": "000000", "password": ADMIN_PASSWORD})
    assert "Heslo nebo kód není správný." in refused.get_data(as_text=True)

    admin_client.post("/admin/account/totp", data={
        "csrf_token": token, "code": pyotp.TOTP(secret).now(), "password": ADMIN_PASSWORD})
    assert admin(app).totp_enabled
    assert "totp.enabled" in audit_actions(app)

    # A new browser logs in with the app instead of the PIN and gets a notice
    # by e-mail. The clock moves one step on: the setup code is already spent.
    browser = https_client(app)
    browser.environ_base["REMOTE_ADDR"] = "198.51.100.7"
    login_token = start_login(app, browser)
    later = totp._now() + timedelta(seconds=30)
    code = pyotp.TOTP(secret).at(later)
    original_now = totp._now
    totp._now = lambda: later
    try:
        response = browser.post("/admin/login/verify", data={"csrf_token": login_token, "method": "totp", "code": code})
        assert response.status_code == 302
        assert "ověřovací aplikac" in outbox(app)[-1]["Subject"]

        # The same code cannot be used twice.
        again = https_client(app)
        again.environ_base["REMOTE_ADDR"] = "198.51.100.8"
        token2 = start_login(app, again)
        replay = again.post("/admin/login/verify", data={"csrf_token": token2, "method": "totp", "code": code})
        assert replay.status_code == 200
    finally:
        totp._now = original_now


def test_totp_secret_is_stored_encrypted(app, admin_client):
    admin_client.get("/admin/account/totp")
    stored = admin(app).totp_pending_secret
    with app.app_context():
        secret = totp.decrypt(stored)
    assert secret and secret not in stored


# --- Command line ---------------------------------------------------------------------------------

def test_create_admin_command(app):
    result = app.test_cli_runner().invoke(
        args=["evrima", "create-admin", "Boss@Example.com", "--name", "Boss"],
        input="short\nshort\n" + NEW_PASSWORD + "\n" + NEW_PASSWORD + "\n")
    assert result.exit_code == 0, result.output
    assert "at least 12 characters" in result.output
    created = admin(app, "boss@example.com")
    assert created.name == "Boss" and not created.is_invited


def test_set_admin_email_command_ends_sessions(app, admin_client):
    result = app.test_cli_runner().invoke(args=["evrima", "set-admin-email", ADMIN_EMAIL, "new@example.com"])
    assert result.exit_code == 0, result.output
    assert admin(app, "new@example.com") is not None
    assert admin_client.get("/admin/").status_code == 302


# --- Language -------------------------------------------------------------------------------------

def test_language_is_saved_to_the_account(app, admin_client):
    admin_client.post("/admin/language", data={
        "csrf_token": csrf_token(admin_client, "/admin/"), "language": "en", "next": "/admin/"})
    assert admin(app).language == "en"
    fresh = https_client(app)
    fresh.environ_base["REMOTE_ADDR"] = "198.51.100.9"
    log_in(app, fresh)
    assert '<html lang="en">' in fresh.get("/admin/").get_data(as_text=True)


# --- Editing administrators ---------------------------------------------------------------------

def edit(client, person_id, **data):
    """Submit the edit dialog of an administrator."""
    form = {"csrf_token": csrf_token(client, "/admin/administrators"), "name": "", "language": "cs", **data}
    return client.post(f"/admin/administrators/{person_id}/edit", data=form)


def test_edit_name_language_and_email_of_another_admin(app, admin_client):
    other_id = add_admin(app, email="kolega@exmaple.com")
    other = https_client(app)
    other.environ_base["REMOTE_ADDR"] = "198.51.100.20"
    log_in(app, other, email="kolega@exmaple.com")

    edit(admin_client, other_id, name="Kolega", language="en", email="kolega@example.com")
    fixed = admin(app, "kolega@example.com")
    assert (fixed.name, fixed.language) == ("Kolega", "en")
    assert other.get("/admin/").status_code == 302                  # logged out by the change
    assert "admin.email_changed" in audit_actions(app)


def test_email_typo_of_invited_person_resends_invitation(app, admin_client):
    token = csrf_token(admin_client, "/admin/administrators")
    admin_client.post("/admin/administrators/invite", data={"csrf_token": token, "email": "novy@exmaple.com"})
    old_link = reset_link(app)
    invited = admin(app, "novy@exmaple.com")

    edit(admin_client, invited.id, email="novy@example.com")
    assert outbox(app)[-1]["To"] == "novy@example.com"
    # The link sent to the mistyped address no longer works.
    assert admin_client.get(old_link).headers["Location"] == "/admin/login"


def test_cannot_change_own_email(app, admin_client):
    me = admin(app)
    edit(admin_client, me.id, email="elsewhere@example.com", name="Me")
    assert admin(app).email == ADMIN_EMAIL
    assert admin(app).name == "Me"


def test_cannot_set_own_password_without_the_current_one(app, admin_client):
    """The edit dialog skips the current-password check, so it refuses one's own account."""
    me = admin(app)
    edit(admin_client, me.id, email=ADMIN_EMAIL, password=NEW_PASSWORD, confirm=NEW_PASSWORD)
    assert admin(app).password_hash == me.password_hash
    assert "password.set_by_admin" not in audit_actions(app)


def test_set_password_for_another_admin(app, admin_client):
    other_id = add_admin(app, email="other@example.com")
    response = edit(admin_client, other_id, email="other@example.com", password="short", confirm="short")
    assert "Heslo musí mít aspoň 12 znaků." in admin_client.get(response.headers["Location"]).get_data(as_text=True)

    edit(admin_client, other_id, email="other@example.com", password=NEW_PASSWORD, confirm=NEW_PASSWORD)
    assert log_in(app, https_client(app), email="other@example.com", password=ADMIN_PASSWORD).status_code == 200
    assert log_in(app, https_client(app), email="other@example.com", password=NEW_PASSWORD).status_code == 302
    assert "password.set_by_admin" in audit_actions(app)


def test_edit_rejects_an_email_in_use(app, admin_client):
    other_id = add_admin(app, email="other@example.com")
    response = edit(admin_client, other_id, email=ADMIN_EMAIL)
    assert "Tento e-mail už patří administrátorovi." in admin_client.get(response.headers["Location"]).get_data(as_text=True)
    assert admin(app, "other@example.com") is not None


def test_send_reset_link_to_another_admin(app, admin_client):
    other_id = add_admin(app, email="other@example.com")
    admin_client.post(f"/admin/administrators/{other_id}/reset",
                      data={"csrf_token": csrf_token(admin_client, "/admin/administrators")})
    assert outbox(app)[-1]["To"] == "other@example.com"
    assert "/admin/password/set/" in outbox(app)[-1].get_content()


@pytest.mark.parametrize("path", ["/admin/administrators", "/admin/account"])
def test_field_ids_are_unique(app, admin_client, path):
    add_admin(app, email="other@example.com")
    html = admin_client.get(path).get_data(as_text=True)
    ids = re.findall(r'\sid="([^"]+)"', html)
    assert len(ids) == len(set(ids)), sorted(i for i in ids if ids.count(i) > 1)
