from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import requests


class CookieSessionStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.metadata: dict[str, Any] = {}

    def load(self, session: requests.Session) -> bool:
        self.metadata = {}
        if not self.path.exists():
            return False
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            cookies = payload.get("cookies", [])
            if not isinstance(cookies, list) or not cookies:
                return False
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
                session.cookies.set(cookie["name"], cookie["value"], **kwargs)
            metadata = payload.get("metadata", {})
            if isinstance(metadata, dict):
                self.metadata = metadata
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
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        tmp.replace(self.path)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass
        self.metadata = dict(metadata or {})

    def clear(self) -> None:
        self.metadata = {}
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass
