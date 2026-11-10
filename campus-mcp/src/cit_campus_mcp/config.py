from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _env_int(name: str, default: int) -> int:
    value = _env(name)
    return int(value) if value else default


def _env_float(name: str, default: float) -> float:
    value = _env(name)
    return float(value) if value else default


@dataclass(frozen=True)
class PortalConfig:
    entry_url: str = _env("CIT_PORTAL_ENTRY_URL", "https://portal.chibatech.ac.jp/")
    app_base: str = _env("CIT_PORTAL_APP_BASE", "https://portal.chibatech.ac.jp")
    top_path: str = _env("CIT_PORTAL_TOP_PATH", "/uprx/up/pk/pky001/Pky00101.xhtml")
    home_path: str = _env("CIT_PORTAL_HOME_PATH", "/uprx/up/bs/bsa001/Bsa00101.xhtml")
    user_field: str = _env("CIT_PORTAL_USER_FIELD")
    password_field: str = _env("CIT_PORTAL_PASSWORD_FIELD")
    otp_field: str = _env("CIT_PORTAL_OTP_FIELD")
    login_submit_field: str = _env("CIT_PORTAL_LOGIN_SUBMIT_FIELD")
    otp_submit_field: str = _env("CIT_PORTAL_OTP_SUBMIT_FIELD")
    otp_credential_field: str = _env("CIT_PORTAL_OTP_CREDENTIAL_FIELD", "selectedCredentialId")
    remember_me_field: str = _env("CIT_PORTAL_REMEMBER_ME_FIELD", "rememberMe")
    remember_me_value: str = _env("CIT_PORTAL_REMEMBER_ME_VALUE", "on")
    totp_credential_label: str = _env("CIT_PORTAL_TOTP_CREDENTIAL_LABEL", "Python")
    totp_digits: int = _env_int("CIT_PORTAL_TOTP_DIGITS", 6)
    totp_interval: int = _env_int("CIT_PORTAL_TOTP_INTERVAL", 30)
    totp_algorithm: str = _env("CIT_PORTAL_TOTP_ALGORITHM", "SHA1").upper()
    totp_min_validity_seconds: float = _env_float("CIT_PORTAL_TOTP_MIN_VALIDITY_SECONDS", 5.0)
    totp_rollover_guard_seconds: float = _env_float("CIT_PORTAL_TOTP_ROLLOVER_GUARD_SECONDS", 0.25)
    totp_max_attempts: int = _env_int("CIT_PORTAL_TOTP_MAX_ATTEMPTS", 2)
    timeout: int = 20
    max_auth_steps: int = 12

    @property
    def top_url(self) -> str:
        return self.app_base.rstrip("/") + "/" + self.top_path.lstrip("/")

    @property
    def home_url(self) -> str:
        return self.app_base.rstrip("/") + "/" + self.home_path.lstrip("/")


@dataclass(frozen=True)
class ManabaConfig:
    base_url: str = _env("CIT_MANABA_BASE", "https://cit.manaba.jp")
    login_path: str = _env("CIT_MANABA_LOGIN_PATH", "/ct/login")
    course_path: str = _env("CIT_MANABA_COURSE_PATH", "/ct/course")
    user_field: str = _env("CIT_MANABA_USER_FIELD")
    password_field: str = _env("CIT_MANABA_PASSWORD_FIELD")
    timeout: int = 20

    @property
    def login_url(self) -> str:
        return self.base_url.rstrip("/") + "/" + self.login_path.lstrip("/")

    @property
    def course_url(self) -> str:
        return self.base_url.rstrip("/") + "/" + self.course_path.lstrip("/")


@dataclass(frozen=True)
class DocumentsConfig:
    base_url: str = _env("CIT_DOCS_BASE", "https://kmsk.is.it-chiba.ac.jp/portal/")
    max_pages: int = _env_int("CIT_DOCS_MAX_PAGES", 100)
    timeout: int = _env_int("CIT_DOCS_TIMEOUT", 20)
    delay_seconds: float = _env_float("CIT_DOCS_DELAY", 0.2)


def session_dir() -> Path:
    raw = _env("CIT_SESSION_DIR", "~/.config/cit-campus-mcp")
    path = Path(raw).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    try:
        path.chmod(0o700)
    except OSError:
        pass
    return path
