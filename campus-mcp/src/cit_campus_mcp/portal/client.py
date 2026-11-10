from __future__ import annotations

import time
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from threading import RLock
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from ..config import PortalConfig
from ..errors import SessionExpired, StructureChanged
from ..session_store import session_lock
from ..webforms import portal_page
from .auth import PortalAuthenticator, PortalAuthResult


class PortalNavigationError(StructureChanged):
    pass


@dataclass
class PortalTopPage:
    session: requests.Session
    soup: BeautifulSoup
    config: PortalConfig

    def menu_post(self, menu_id: str, target_path: str | None = None) -> BeautifulSoup:
        menu_form = self.soup.select_one("form#menuForm")
        if menu_form is None:
            raise PortalNavigationError("Portal menu form was not found. The session may have expired.")
        data = {
            tag.get("name", ""): tag.get("value", "")
            for tag in menu_form.select('input[type="hidden"]')
            if tag.get("name")
        }
        data.update(
            {
                "rx.sync.source": "menuForm:mainMenu",
                "menuForm:mainMenu": "menuForm:mainMenu",
                "menuForm:mainMenu_menuid": menu_id,
            }
        )
        response = self.session.post(
            urljoin(
                self.config.app_base.rstrip("/") + "/",
                target_path or str(menu_form.get("action") or self.config.home_url),
            ),
            data=data,
            timeout=self.config.timeout,
            allow_redirects=True,
        )
        response.raise_for_status()
        page = portal_page(response)
        if page.select_one("form#menuForm"):
            self.soup = page
        return page


class PortalClient:
    def __init__(self, authenticator: PortalAuthenticator | None = None) -> None:
        self.authenticator = authenticator or PortalAuthenticator()
        self.auth: PortalAuthResult | None = None
        self.lock = RLock()
        self.cache: dict[str, tuple[float, object]] = {}
        self.cache_ttl = 30.0
        self.clock = time.monotonic

    def connect(self, force: bool = False) -> PortalTopPage:
        with self.lock:
            return self._connect(force)

    def _connect(self, force: bool = False) -> PortalTopPage:
        if self.auth is None or force:
            self.auth = self.authenticator.login(force=force)
        return PortalTopPage(
            session=self.auth.session,
            soup=self.auth.soup,
            config=self.authenticator.config,
        )

    def run(self, key: str, parser: Callable[[PortalTopPage], object], *, refresh: bool = False) -> object:
        # JSF ViewState and Session cookies are mutable. Serialize the whole operation,
        # including parsing/pagination, both within this process and across MCP hosts.
        with self.lock, session_lock(self.authenticator.store.path.with_name("portal-operation.lock")):
            if not refresh and key in self.cache:
                created, value = self.cache[key]
                if self.clock() - created < self.cache_ttl:
                    return deepcopy(value)
            for attempt in range(2):
                try:
                    top = self.connect()
                    value = parser(top)
                    if self.auth is not None:
                        self.auth.soup = top.soup
                    self.cache[key] = (self.clock(), deepcopy(value))
                    return value
                except SessionExpired:
                    self.cache.clear()
                    if self.auth is not None:
                        self.auth.session.close()
                    self.auth = None
                    if attempt:
                        raise
            raise SessionExpired("Portal session could not be restored.")

    def status(self) -> dict[str, object]:
        def read_status(top):
            # Probe a read-only list; a local object alone does not prove remote validity.
            top.menu_post("0_3_0_0")
            return {
                "authenticated": True,
                "restored_session": bool(self.auth and self.auth.restored),
                "portal_host": self.auth.response.url.split("/", 3)[2] if self.auth else "",
                "menu_form": bool(top.soup.select_one("form#menuForm")),
            }

        return self.run("status", read_status, refresh=True)
