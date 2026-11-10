from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from ..config import PortalConfig
from .auth import PortalAuthResult, PortalAuthenticator


class PortalNavigationError(RuntimeError):
    pass


@dataclass
class PortalTopPage:
    session: requests.Session
    soup: BeautifulSoup
    config: PortalConfig

    def menu_post(self, menu_id: str, target_path: str = "/uprx/up/bs/bsa001/Bsa00101.xhtml") -> BeautifulSoup:
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
            urljoin(self.config.app_base.rstrip("/") + "/", target_path.lstrip("/")),
            data=data,
            timeout=self.config.timeout,
            allow_redirects=True,
        )
        response.raise_for_status()
        return BeautifulSoup(response.content, "xml")


class PortalClient:
    def __init__(self, authenticator: PortalAuthenticator | None = None) -> None:
        self.authenticator = authenticator or PortalAuthenticator()
        self.auth: PortalAuthResult | None = None

    def connect(self, force: bool = False) -> PortalTopPage:
        self.auth = self.authenticator.login(force=force)
        return PortalTopPage(
            session=self.auth.session,
            soup=self.auth.soup,
            config=self.authenticator.config,
        )

    def status(self) -> dict[str, object]:
        top = self.connect()
        return {
            "authenticated": True,
            "restored_session": bool(self.auth and self.auth.restored),
            "portal_host": self.auth.response.url.split("/", 3)[2] if self.auth else "",
            "menu_form": bool(top.soup.select_one("form#menuForm")),
        }
