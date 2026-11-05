"""TOTP codes from an authenticator app, as an optional replacement for the e-mailed PIN.

TOTP is off by default. It is a safety net for when the mail server fails and
no PIN arrives (docs/framework.md, "Admin login"). Enabling and disabling it
needs the password and a valid code, and both are written to the audit log.

The secret is stored encrypted (Fernet). The key is derived from SECRET_KEY,
so a leaked database backup alone does not reveal it. Changing SECRET_KEY
makes stored TOTP secrets unreadable: those users simply set TOTP up again;
the PIN by e-mail keeps working meanwhile.
"""

import base64
from datetime import datetime

import pyotp
import qrcode
import qrcode.image.svg
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from flask import current_app
from markupsafe import Markup

ISSUER = "Evrima"
# One time step (30 s) either way tolerates a phone clock that is slightly off.
VALID_WINDOW = 1


def _fernet() -> Fernet:
    """The cipher for TOTP secrets, keyed from SECRET_KEY."""
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=None,
               info=b"evrima totp secret").derive(current_app.config["SECRET_KEY"].encode())
    return Fernet(base64.urlsafe_b64encode(key))


def new_secret() -> str:
    """A fresh random TOTP secret (base32, as authenticator apps expect)."""
    return pyotp.random_base32()


def encrypt(secret: str) -> str:
    """Encrypt a secret for storage."""
    return _fernet().encrypt(secret.encode()).decode()


def decrypt(stored: str | None) -> str | None:
    """Decrypt a stored secret; None when it is missing or no longer readable."""
    if not stored:
        return None
    try:
        return _fernet().decrypt(stored.encode()).decode()
    except InvalidToken:
        current_app.logger.warning("A stored TOTP secret cannot be decrypted (SECRET_KEY changed?).")
        return None


def provisioning_uri(secret: str, email: str, site: str) -> str:
    """The otpauth:// address an authenticator app reads from the QR code."""
    return pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name=f"{ISSUER} {site}".strip())


def qr_svg(uri: str) -> Markup:
    """The QR code as inline SVG.

    Inline SVG instead of a data: image, which the CSP does not allow; the
    generated SVG uses presentation attributes only, no style attributes.
    """
    image = qrcode.make(uri, image_factory=qrcode.image.svg.SvgPathImage)
    return Markup(image.to_string(encoding="unicode"))


def matching_step(secret: str, code: str, last_step: int | None) -> int | None:
    """Return the time step `code` belongs to, or None if it is not valid.

    A code whose step is not newer than `last_step` is refused: a code seen
    over someone's shoulder cannot be used a second time.
    """
    code = "".join(code.split())
    if not (code.isdigit() and len(code) == 6):
        return None
    totp = pyotp.TOTP(secret)
    now_step = totp.timecode(_now())
    for step in range(now_step - VALID_WINDOW, now_step + VALID_WINDOW + 1):
        if last_step is not None and step <= last_step:
            continue
        if pyotp.utils.strings_equal(totp.generate_otp(step), code):
            return step
    return None


def _now() -> datetime:
    """Current local time, as pyotp expects it; a function so tests can move the clock."""
    return datetime.now()
