from __future__ import annotations

import base64
import hashlib
import hmac
import struct
import time


class TOTPError(ValueError):
    pass


def generate_totp(
    secret: str,
    *,
    timestamp: int | float | None = None,
    digits: int = 6,
    interval: int = 30,
    algorithm: str = "SHA1",
) -> str:
    """Generate an RFC 6238 TOTP code using only the Python standard library."""
    if digits <= 0 or digits > 10:
        raise TOTPError("digits must be between 1 and 10")
    if interval <= 0:
        raise TOTPError("interval must be positive")
    normalized = "".join(secret.split()).upper()
    padding = "=" * ((8 - len(normalized) % 8) % 8)
    try:
        key = base64.b32decode(normalized + padding, casefold=True)
    except Exception as exc:
        raise TOTPError("Invalid Base32 TOTP secret") from exc

    digestmod = {
        "SHA1": hashlib.sha1,
        "SHA256": hashlib.sha256,
        "SHA512": hashlib.sha512,
    }.get(algorithm.upper())
    if digestmod is None:
        raise TOTPError(f"Unsupported TOTP algorithm: {algorithm}")

    now = time.time() if timestamp is None else float(timestamp)
    counter = int(now // interval)
    message = struct.pack(">Q", counter)
    digest = hmac.new(key, message, digestmod).digest()
    offset = digest[-1] & 0x0F
    binary = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(binary % (10**digits)).zfill(digits)
