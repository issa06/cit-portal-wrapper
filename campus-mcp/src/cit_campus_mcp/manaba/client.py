from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from ..config import ManabaConfig, session_dir
from ..credentials import manaba_credentials
from ..http import SafeSession
from ..session_store import CookieSessionStore
from ..webforms import find_credential_form, soup_from_response, submit_form

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ja,en-US;q=0.8,en;q=0.6",
}


@dataclass
class ManabaCourse:
    course_id: str
    name: str
    url: str


class ManabaClient:
    def __init__(self, config: ManabaConfig | None = None) -> None:
        self.config = config or ManabaConfig()
        self.session = SafeSession({urlparse(self.config.base_url).hostname})
        self.session.headers.update(DEFAULT_HEADERS)
        self.store = CookieSessionStore(session_dir() / "manaba-session.json")
        self.connected = False

    @staticmethod
    def _looks_logged_in(soup: BeautifulSoup, url: str) -> bool:
        if soup.find("input", attrs={"type": "password"}):
            return False
        if "/ct/login" in url:
            return False
        return bool(soup.find("a", href=re.compile(r"/ct/(?:course|home)")))

    def connect(self, force: bool = False) -> None:
        if self.connected and not force:
            return
        if not force and self.store.load(self.session):
            response = self.session.get(self.config.course_url, timeout=self.config.timeout, allow_redirects=True)
            soup = soup_from_response(response)
            if self._looks_logged_in(soup, response.url):
                self.connected = True
                return
            self.session.cookies.clear()
            self.store.clear()

        creds = manaba_credentials()
        response = self.session.get(self.config.login_url, timeout=self.config.timeout, allow_redirects=True)
        soup = soup_from_response(response)
        spec = find_credential_form(soup, response.url)
        if spec is None:
            raise RuntimeError("Could not find the manaba login form.")
        user_field = self.config.user_field or spec.user_field
        password_field = self.config.password_field or spec.password_field
        if not user_field or not password_field:
            raise RuntimeError("Could not determine manaba login field names.")
        response = submit_form(
            self.session,
            spec,
            {user_field: creds.user_id, password_field: creds.password},
            self.config.timeout,
        )
        soup = soup_from_response(response)
        if not self._looks_logged_in(soup, response.url):
            # Some installations redirect to /ct/home after login; test the course page explicitly.
            response = self.session.get(self.config.course_url, timeout=self.config.timeout, allow_redirects=True)
            soup = soup_from_response(response)
        if not self._looks_logged_in(soup, response.url):
            raise RuntimeError("manaba login did not reach an authenticated page.")
        self.store.save(self.session)
        self.connected = True

    def get_soup(self, path_or_url: str) -> BeautifulSoup:
        self.connect()
        url = (
            path_or_url
            if path_or_url.startswith("https://")
            else urljoin(self.config.base_url.rstrip("/") + "/", path_or_url.lstrip("/"))
        )
        parsed = urlparse(url)
        if parsed.netloc != urlparse(self.config.base_url).netloc:
            raise ValueError("Refusing to fetch a URL outside the configured manaba host.")
        response = self.session.get(url, timeout=self.config.timeout, allow_redirects=True)
        response.raise_for_status()
        return soup_from_response(response)

    def list_courses(self) -> list[dict[str, str]]:
        soup = self.get_soup(self.config.course_path)
        found: dict[str, ManabaCourse] = {}
        for link in soup.find_all("a", href=True):
            href = str(link.get("href"))
            match = re.search(r"/ct/course_(\d+)(?:$|[/?_])", href)
            if not match:
                continue
            name = link.get_text(" ", strip=True)
            if not name:
                continue
            course_id = match.group(1)
            url = urljoin(self.config.base_url.rstrip("/") + "/", href.lstrip("/"))
            found.setdefault(course_id, ManabaCourse(course_id=course_id, name=name, url=url))
        return [course.__dict__ for course in found.values()]

    def list_action_items(self) -> list[dict[str, str | None]]:
        """Extract task-like links from the authenticated home/course pages without submitting anything."""
        pages = [self.get_soup("/ct/home"), self.get_soup(self.config.course_path)]
        results: list[dict[str, str | None]] = []
        seen: set[str] = set()
        task_pattern = re.compile(r"(レポート|小テスト|アンケート|課題|提出|締切|期限|report|quiz|survey)", re.I)
        for soup in pages:
            for link in soup.find_all("a", href=True):
                text = link.get_text(" ", strip=True)
                href = str(link.get("href"))
                if not text or not task_pattern.search(text + " " + href):
                    continue
                url = urljoin(self.config.base_url.rstrip("/") + "/", href.lstrip("/"))
                if url in seen:
                    continue
                seen.add(url)
                parent_text = link.parent.get_text(" ", strip=True) if link.parent else text
                results.append({"title": text, "context": parent_text[:500], "url": url})
        return results

    def get_page_text(self, path_or_url: str) -> dict[str, str]:
        soup = self.get_soup(path_or_url)
        title = soup.title.get_text(" ", strip=True) if soup.title else ""
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        return {"title": title, "text": soup.get_text("\n", strip=True)[:50000]}
