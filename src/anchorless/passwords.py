"""The settings password as a hash, so a config file can hold it without revealing it.

    anchorless hash-password      ->  scrypt$15$8$1$<salt>$<hash>   ([admin] password_hash)

scrypt (in Python's standard library) is slow and memory-hard on purpose: about
50 ms and 32 MB per check, which costs a login nothing and a password guesser a lot.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

MIN_LENGTH = 12
_LOG2_N, _R, _P, _LEN = 15, 8, 1, 32


def _scrypt(password: str, salt: bytes, log2_n: int, r: int, p: int) -> bytes:
    n = 1 << log2_n
    return hashlib.scrypt(password.encode(), salt=salt, n=n, r=r, p=p, dklen=_LEN,
                          maxmem=2 * 128 * n * r + (1 << 20))


def hash_password(password: str) -> str:
    if len(password) < MIN_LENGTH:
        raise ValueError(f"the password must be at least {MIN_LENGTH} characters")
    salt = secrets.token_bytes(16)
    digest = _scrypt(password, salt, _LOG2_N, _R, _P)
    b64 = lambda b: base64.b64encode(b).decode()  # noqa: E731
    return f"scrypt${_LOG2_N}${_R}${_P}${b64(salt)}${b64(digest)}"


def parse_hash(stored: str) -> tuple[int, int, int, bytes, bytes]:
    """Check the format; raises ValueError."""
    parts = stored.split("$")
    if len(parts) != 6 or parts[0] != "scrypt":
        raise ValueError("password_hash must look like scrypt$15$8$1$<salt>$<hash> (from `anchorless hash-password`)")
    try:
        log2_n, r, p = (int(x) for x in parts[1:4])
        salt, digest = base64.b64decode(parts[4], validate=True), base64.b64decode(parts[5], validate=True)
    except ValueError as err:
        raise ValueError("password_hash is not a valid scrypt hash") from err
    if not (10 <= log2_n <= 20 and 1 <= r <= 32 and 1 <= p <= 16 and salt and digest):
        raise ValueError("password_hash has out-of-range scrypt settings")
    return log2_n, r, p, salt, digest


def verify(password: str, stored: str) -> bool:
    log2_n, r, p, salt, digest = parse_hash(stored)
    return hmac.compare_digest(_scrypt(password, salt, log2_n, r, p), digest)
