from __future__ import annotations

import io
import re
import time
from dataclasses import dataclass
from urllib.parse import urldefrag, urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader

from ..config import DocumentsConfig


@dataclass(frozen=True)
class DocumentRecord:
    title: str
    url: str
    kind: str
    text: str = ""


class DocumentsClient:
    def __init__(self, config: DocumentsConfig | None = None) -> None:
        self.config = config or DocumentsConfig()
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "CIT-Campus-MCP/0.1 read-only indexer"})
        self.allowed_host = urlparse(self.config.base_url).netloc

    def _allowed(self, url: str) -> bool:
        return urlparse(url).netloc == self.allowed_host

    def _get(self, url: str) -> requests.Response:
        if not self._allowed(url):
            raise ValueError("Refusing to fetch outside the student documents host.")
        if self.config.delay_seconds > 0:
            time.sleep(self.config.delay_seconds)
        response = self.session.get(url, timeout=self.config.timeout, allow_redirects=True)
        response.raise_for_status()
        return response

    @staticmethod
    def _html_text(content: bytes) -> tuple[str, str, list[tuple[str, str]]]:
        soup = BeautifulSoup(content, "lxml")
        title = soup.title.get_text(" ", strip=True) if soup.title else ""
        links = [(a.get_text(" ", strip=True), str(a.get("href"))) for a in soup.find_all("a", href=True)]
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        text = soup.get_text("\n", strip=True)
        return title, text, links

    @staticmethod
    def _pdf_text(content: bytes) -> str:
        reader = PdfReader(io.BytesIO(content))
        chunks = []
        for page in reader.pages:
            chunks.append(page.extract_text() or "")
        return "\n".join(chunks)

    def list_links(self) -> list[dict[str, str]]:
        response = self._get(self.config.base_url)
        _, _, links = self._html_text(response.content)
        result: list[dict[str, str]] = []
        seen: set[str] = set()
        for label, href in links:
            url = urldefrag(urljoin(response.url, href))[0]
            if not self._allowed(url) or url in seen:
                continue
            seen.add(url)
            result.append({"title": label or url.rsplit("/", 1)[-1], "url": url})
        return result

    def search(self, query: str, limit: int = 20) -> list[dict[str, str]]:
        words = [w.lower() for w in re.split(r"\s+", query.strip()) if w]
        if not words:
            return []
        queue = [self.config.base_url]
        seen: set[str] = set()
        matches: list[dict[str, str]] = []

        while queue and len(seen) < self.config.max_pages and len(matches) < limit:
            url = urldefrag(queue.pop(0))[0]
            if url in seen or not self._allowed(url):
                continue
            seen.add(url)
            try:
                response = self._get(url)
            except requests.RequestException:
                continue
            content_type = response.headers.get("Content-Type", "").lower()
            is_pdf = "application/pdf" in content_type or response.url.lower().endswith(".pdf")
            if is_pdf:
                try:
                    text = self._pdf_text(response.content)
                except Exception:
                    text = ""
                title = response.url.rsplit("/", 1)[-1]
                links: list[tuple[str, str]] = []
                kind = "pdf"
            else:
                title, text, links = self._html_text(response.content)
                kind = "html"

            haystack = (title + "\n" + text).lower()
            if all(word in haystack for word in words):
                snippet_start = min((haystack.find(word) for word in words if word in haystack), default=0)
                snippet = text[max(0, snippet_start - 200):snippet_start + 800].replace("\n", " ")
                matches.append(
                    {
                        "title": title or response.url.rsplit("/", 1)[-1],
                        "url": response.url,
                        "kind": kind,
                        "snippet": snippet[:1000],
                    }
                )

            for label, href in links:
                next_url = urldefrag(urljoin(response.url, href))[0]
                if self._allowed(next_url) and next_url not in seen:
                    queue.append(next_url)

        return matches[:limit]

    def get_text(self, url: str, max_chars: int = 50000) -> dict[str, str]:
        response = self._get(url)
        content_type = response.headers.get("Content-Type", "").lower()
        if "application/pdf" in content_type or response.url.lower().endswith(".pdf"):
            text = self._pdf_text(response.content)
            title = response.url.rsplit("/", 1)[-1]
            kind = "pdf"
        else:
            title, text, _ = self._html_text(response.content)
            kind = "html"
        return {"title": title, "url": response.url, "kind": kind, "text": text[:max_chars]}
