"""Password hashing, random tokens and PINs.

- Passwords: Argon2id (argon2-cffi defaults: 64 MiB, 3 iterations, 4 lanes),
  above the OWASP minimum (docs/framework.md, decided 2026-10-14).
- Tokens in cookies and links: 256 random bits; the database keeps SHA-256.
  A fast hash is enough here because the token itself cannot be guessed.
- PINs: only a million values, so a plain hash could be reversed by trying
  them all. The database keeps an HMAC keyed with SECRET_KEY instead, which a
  leaked backup alone cannot reverse.
"""

import hashlib
import hmac
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from flask import current_app

PASSWORD_MIN_LENGTH = 12
# Argon2 handles long input, but there is no reason to accept megabytes.
PASSWORD_MAX_LENGTH = 1024

# OWASP's minimum for Argon2id (m = 19 MiB, t = 2, p = 1), decided 2026-11-06
# after the security audit. The library default (64 MiB, t = 3, p = 4) made a
# flood of login attempts cost up to half a gigabyte of memory per website on a
# shared server. Hashes made with other parameters are redone at the next login
# (needs_rehash).
_hasher = PasswordHasher(time_cost=2, memory_cost=19 * 1024, parallelism=1)
# Verified when the e-mail is unknown, so the answer takes as long as for a
# real account and the timing does not reveal which e-mails exist.
_DUMMY_HASH = _hasher.hash("evrima-timing-equaliser")


def password_problem(password: str) -> str | None:
    """Return the catalogue key of the problem with `password`, or None if it is acceptable.

    Only the length is checked: a long password protects better than forced
    digits and symbols, and is kinder to non-technical users.
    """
    if len(password) < PASSWORD_MIN_LENGTH:
        return "auth.password.too_short"
    if len(password) > PASSWORD_MAX_LENGTH:
        return "auth.password.too_long"
    return None


def hash_password(password: str) -> str:
    """Return the Argon2id hash of `password`."""
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    """Check `password`; a missing hash (unknown user, pending invitation) still costs a verification."""
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    """True when the hash was made with weaker parameters than the current ones."""
    return _hasher.check_needs_rehash(password_hash)


def new_token() -> str:
    """A random token for a cookie or a link (URL-safe, 256 bits)."""
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    """The SHA-256 of a token, as stored in the database."""
    return hashlib.sha256(token.encode()).hexdigest()


def same(a: str, b: str) -> bool:
    """Compare two secrets in constant time."""
    return hmac.compare_digest(a.encode(), b.encode())
