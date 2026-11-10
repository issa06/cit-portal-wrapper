from __future__ import annotations

import fcntl
import json
import os
import stat
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import requests

from .errors import RequestTimeout


@contextmanager
def session_lock(path: Path, timeout: float = 10):
    """Bounded cross-process lock protects the single-use SSO transaction/cache."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    deadline = time.monotonic() + timeout
    try:
        os.fchmod(fd, 0o600)
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise RequestTimeout("Another process is authenticating; retry later.") from None
                time.sleep(0.05)
        yield
    finally:
        os.close(fd)


class CookieSessionStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.metadata: dict[str, Any] = {}

    def load(self, session: requests.Session) -> bool:
        self.metadata = {}
        if not self.path.exists() or self.path.is_symlink():
            return False
        try:
            info = self.path.stat()
            if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077 or info.st_size > 1024 * 1024:
                return False
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            cookies = payload.get("cookies", [])
            if not isinstance(cookies, list) or not cookies:
                return False
            jar = requests.cookies.RequestsCookieJar()
            for cookie in cookies:
                kwargs: dict[str, Any] = {"path": cookie.get("path") or "/"}
                if cookie.get("domain"):
                    kwargs["domain"] = cookie["domain"]
                if cookie.get("secure") is not None:
                    kwargs["secure"] = bool(cookie.get("secure"))
                if cookie.get("expires") is not None:
                    kwargs["expires"] = cookie.get("expires")
                rest = cookie.get("rest")
                if isinstance(rest, dict) and rest:
                    kwargs["rest"] = rest
                jar.set(cookie["name"], cookie["value"], **kwargs)
            metadata = payload.get("metadata", {})
            if isinstance(metadata, dict):
                self.metadata = metadata
            session.cookies.update(jar)
            return True
        except (OSError, ValueError, KeyError, TypeError):
            self.metadata = {}
            return False

    def save(self, session: requests.Session, *, metadata: dict[str, Any] | None = None) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        cookies = []
        for cookie in session.cookies:
            cookies.append(
                {
                    "name": cookie.name,
                    "value": cookie.value,
                    "domain": cookie.domain,
                    "path": cookie.path,
                    "secure": cookie.secure,
                    "expires": cookie.expires,
                    "rest": dict(getattr(cookie, "_rest", {}) or {}),
                }
            )
        payload: dict[str, Any] = {"version": 2, "cookies": cookies}
        if metadata:
            payload["metadata"] = metadata
        fd, name = tempfile.mkstemp(prefix=".session-", dir=self.path.parent)
        tmp = Path(name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False)
                handle.flush()
                os.fsync(handle.fileno())
            tmp.replace(self.path)
        finally:
            tmp.unlink(missing_ok=True)
        self.metadata = dict(metadata or {})

    def clear(self) -> None:
        self.metadata = {}
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass
