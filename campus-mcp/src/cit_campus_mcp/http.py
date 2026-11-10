"""HTTPS host checks include every redirect; authentication POSTs are never retried."""

from __future__ import annotations

from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .errors import AuthenticationError, ResponseTooLarge


class ReadRetry(Retry):
    def get_backoff_time(self) -> float:
        return min(2.0, max(0.5, super().get_backoff_time())) if self.history else 0.0


class SafeSession(requests.Session):
    def __init__(self, hosts: set[str]) -> None:
        super().__init__()
        self.hosts = hosts
        # GET only: no automatic replay of password, OTP, SAML or JSF POSTs.
        retries = ReadRetry(
            total=1,
            connect=0,
            read=0,
            status=1,
            backoff_factor=0.5,
            status_forcelist=[502, 503, 504],
            allowed_methods={"GET"},
            respect_retry_after_header=False,
            raise_on_status=False,
        )
        self.mount("https://", HTTPAdapter(max_retries=retries))

    def validate_url(self, url: str) -> None:
        parsed = urlparse(url)
        if (
            parsed.scheme != "https"
            or parsed.hostname not in self.hosts
            or parsed.username
            or parsed.password
            or parsed.port not in (None, 443)
        ):
            raise AuthenticationError("Blocked URL outside the configured HTTPS hosts.")

    def get_redirect_target(self, response: requests.Response) -> str | None:
        from urllib.parse import urljoin

        target = super().get_redirect_target(response)
        if target:
            self.validate_url(urljoin(response.url, target))
        return target

    def request(self, method: str, url: str, **kwargs) -> requests.Response:
        import anyio

        try:
            anyio.from_thread.check_cancelled()
        except RuntimeError:
            pass  # Direct CLI use has no AnyIO worker context.
        self.validate_url(url)
        kwargs.setdefault("timeout", 20)
        # Stream limits apply before parsing or buffering private pages.
        kwargs["stream"] = True
        response = super().request(method, url, **kwargs)
        try:
            response.raise_for_status()
            chunks, size = [], 0
            for chunk in response.iter_content(65536):
                size += len(chunk)
                if size > 8 * 1024 * 1024:
                    raise ResponseTooLarge("Remote page exceeds the download limit.")
                chunks.append(chunk)
            response._content = b"".join(chunks)
            response._content_consumed = True
            return response
        finally:
            response.close()
