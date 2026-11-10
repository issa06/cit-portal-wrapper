from __future__ import annotations

import os
import platform
import subprocess
from dataclasses import dataclass, field
from getpass import getpass

from .errors import AuthenticationError

SERVICE = "cit-campus-mcp"


@dataclass(frozen=True)
class Credentials:
    user_id: str = field(repr=False)
    password: str = field(repr=False)
    totp_secret: str | None = field(default=None, repr=False)


def _security_get(account: str) -> str | None:
    if platform.system() != "Darwin":
        return None
    try:
        result = subprocess.run(
            ["/usr/bin/security", "find-generic-password", "-w", "-s", SERVICE, "-a", account],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.rstrip("\n")
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def _security_set(account: str, value: str) -> None:
    if platform.system() != "Darwin":
        raise RuntimeError("Interactive credential storage currently supports macOS Keychain only.")
    subprocess.run(
        [
            "/usr/bin/security",
            "add-generic-password",
            "-U",
            "-s",
            SERVICE,
            "-a",
            account,
            "-w",
            value,
        ],
        check=True,
        stdout=subprocess.DEVNULL,
    )


def _get(account: str, env_name: str) -> str | None:
    value = os.getenv(env_name)
    if value:
        return value if account.endswith("password") else value.strip()
    return _security_get(account)


def portal_credentials() -> Credentials:
    user_id = _get("portal.user_id", "CIT_PORTAL_USER_ID")
    password = _get("portal.password", "CIT_PORTAL_PASSWORD")
    totp_secret = _get("portal.totp_secret", "CIT_PORTAL_TOTP_SECRET")
    missing = [
        name
        for name, value in (
            ("portal.user_id", user_id),
            ("portal.password", password),
        )
        if not value
    ]
    if missing:
        raise AuthenticationError("Missing Portal credentials: " + ", ".join(missing) + ". Run `cit-campus-keyring`.")
    return Credentials(user_id=user_id or "", password=password or "", totp_secret=totp_secret)


def manaba_credentials() -> Credentials:
    user_id = _get("manaba.user_id", "CIT_MANABA_USER_ID")
    password = _get("manaba.password", "CIT_MANABA_PASSWORD")
    missing = [name for name, value in (("manaba.user_id", user_id), ("manaba.password", password)) if not value]
    if missing:
        raise AuthenticationError("Missing manaba credentials: " + ", ".join(missing) + ". Run `cit-campus-keyring`.")
    return Credentials(user_id=user_id or "", password=password or "")


def interactive_setup() -> None:
    if platform.system() != "Darwin":
        raise RuntimeError("Use environment variables on non-macOS systems for this prototype.")
    print("Store credentials in macOS Keychain. Values are not written to project files.")
    portal_user = input("Portal user ID: ").strip()
    portal_password = getpass("Portal password: ")
    portal_totp = getpass("Portal TOTP secret (Base32): ").replace(" ", "").strip()
    if portal_user:
        _security_set("portal.user_id", portal_user)
    if portal_password:
        _security_set("portal.password", portal_password)
    if portal_totp:
        _security_set("portal.totp_secret", portal_totp)

    setup_manaba = input("Store manaba credentials too? [y/N]: ").strip().lower() == "y"
    if setup_manaba:
        manaba_user = input("manaba user ID: ").strip()
        manaba_password = getpass("manaba password: ")
        if manaba_user:
            _security_set("manaba.user_id", manaba_user)
        if manaba_password:
            _security_set("manaba.password", manaba_password)
    print("Saved to macOS Keychain.")
