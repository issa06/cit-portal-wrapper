from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import timezone
from email.utils import parsedate_to_datetime
from threading import RLock
from typing import Callable
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from ..config import PortalConfig, session_dir
from ..credentials import Credentials, portal_credentials
from ..errors import MFARequired
from ..http import SafeSession
from ..session_store import CookieSessionStore, session_lock
from ..totp import generate_totp
from ..webforms import (
    AuthenticationError,
    find_auto_post_form,
    find_client_redirect,
    find_credential_form,
    find_form_by_id,
    find_otp_credentials,
    find_otp_form,
    find_sso_entry_url,
    select_otp_credential_id,
    soup_from_response,
    submit_form,
)

TRANSIENT_SSO_COOKIE_NAMES = {
    "AUTH_SESSION_ID",
    "AUTH_SESSION_ID_LEGACY",
    "KC_AUTH_SESSION_HASH",
    "KC_RESTART",
}


DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ja,en-US;q=0.8,en;q=0.6",
}


@dataclass
class PortalAuthResult:
    session: requests.Session
    response: requests.Response
    soup: BeautifulSoup
    restored: bool = False


@dataclass(frozen=True)
class TotpTiming:
    timestamp: float
    remaining_seconds: float
    server_offset_seconds: float
    clock_source: str
    waited_seconds: float = 0.0


class PortalAuthenticator:
    def __init__(
        self,
        config: PortalConfig | None = None,
        credentials_provider: Callable[[], Credentials] = portal_credentials,
        clock: Callable[[], float] = time.time,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.config = config or PortalConfig()
        self.credentials_provider = credentials_provider
        self.clock = clock
        self.sleeper = sleeper
        self.store = CookieSessionStore(session_dir() / "portal-session.json")
        self.last_response: requests.Response | None = None
        self.trace: list[dict[str, object]] = []
        self._lock = RLock()

    def new_session(self) -> requests.Session:
        session = SafeSession(
            {urlparse(self.config.app_base).hostname, urlparse(self.config.entry_url).hostname, "sso.chibatech.ac.jp"}
        )
        session.headers.update(DEFAULT_HEADERS)
        return session

    @staticmethod
    def is_authenticated(soup: BeautifulSoup, response: requests.Response) -> bool:
        if soup.select_one("form#menuForm"):
            return True
        if soup.select_one("#menuForm") and "uprx" in response.url:
            return True
        return False

    @staticmethod
    def _http_date_timestamp(response: requests.Response) -> float | None:
        value = response.headers.get("Date") if response.headers is not None else None
        if not value:
            return None
        try:
            parsed = parsedate_to_datetime(value)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.timestamp()
        except (TypeError, ValueError, OverflowError):
            return None

    def _server_clock_offset(self, response: requests.Response) -> tuple[float, str]:
        server_timestamp = self._http_date_timestamp(response)
        if server_timestamp is None:
            return 0.0, "local"
        return server_timestamp - self.clock(), "http-date"

    def _prepare_totp(
        self,
        secret: str,
        response: requests.Response,
        *,
        after_counter: int | None = None,
    ) -> tuple[str, TotpTiming, int]:
        interval = float(self.config.totp_interval)
        if interval <= 0:
            raise AuthenticationError("Portal TOTP interval must be positive.")

        offset, source = self._server_clock_offset(response)
        effective_now = self.clock() + offset
        counter = int(effective_now // interval)
        remaining = interval - (effective_now % interval)
        wait_seconds = 0.0

        if after_counter is not None and counter <= after_counter:
            next_window = (after_counter + 1) * interval
            wait_seconds = max(
                wait_seconds,
                next_window - effective_now + self.config.totp_rollover_guard_seconds,
            )

        if remaining < self.config.totp_min_validity_seconds:
            wait_seconds = max(
                wait_seconds,
                remaining + self.config.totp_rollover_guard_seconds,
            )

        if wait_seconds > 0:
            self.sleeper(wait_seconds)
            effective_now = self.clock() + offset
            counter = int(effective_now // interval)
            remaining = interval - (effective_now % interval)

        code = generate_totp(
            secret,
            timestamp=effective_now,
            digits=self.config.totp_digits,
            interval=self.config.totp_interval,
            algorithm=self.config.totp_algorithm,
        )
        timing = TotpTiming(
            timestamp=effective_now,
            remaining_seconds=remaining,
            server_offset_seconds=offset,
            clock_source=source,
            waited_seconds=max(0.0, wait_seconds),
        )
        return code, timing, counter

    @staticmethod
    def _https_get(session: requests.Session, url: str, timeout: int) -> requests.Response:
        parsed = urlparse(url)
        if parsed.scheme and parsed.scheme != "https":
            raise AuthenticationError("Refusing authentication redirect to non-HTTPS URL.")
        return session.get(url, timeout=timeout, allow_redirects=True)

    def _restore_candidate_urls(self) -> list[str]:
        portal_host = urlparse(self.config.app_base).netloc
        candidates: list[str] = [self.config.home_url]

        last_url = self.store.metadata.get("last_authenticated_url")
        if isinstance(last_url, str):
            parsed = urlparse(last_url)
            if parsed.scheme == "https" and parsed.netloc == portal_host and parsed.path.startswith("/uprx/"):
                candidates.append(last_url)

        # Compatibility with r1.2-r1.4 caches. Pky00102.xhtml is the post-SAML
        # bridge URL, but the actual authenticated application home is Bsa00101.
        candidates.append(self.config.app_base.rstrip("/") + "/uprx/up/pk/pky001/Pky00102.xhtml")
        candidates.append(self.config.top_url)
        return list(dict.fromkeys(candidates))

    def _save_session(self, session: requests.Session, response: requests.Response) -> None:
        self.store.save(
            session,
            metadata={
                "last_authenticated_url": self.config.home_url,
                "canonical_home_url": self.config.home_url,
            },
        )

    def _record_restore(self, action: str, **extra: object) -> None:
        entry: dict[str, object] = {
            "phase": "restore",
            "action": action,
        }
        entry.update(
            {
                k: v
                for k, v in extra.items()
                if k
                in {
                    "step",
                    "authenticated",
                    "has_sso_entry",
                    "has_credentials",
                    "has_otp",
                    "has_auto_post",
                    "has_login_form",
                    "cookie_count",
                    "error",
                }
            }
        )
        self.trace.append(entry)

    @staticmethod
    def _safe_cookie_inventory(session: requests.Session) -> list[dict[str, object]]:
        inventory: list[dict[str, object]] = []
        for cookie in session.cookies:
            inventory.append(
                {
                    "name": cookie.name,
                    "domain": cookie.domain,
                    "path": cookie.path,
                    "secure": bool(cookie.secure),
                    "expires": cookie.expires,
                }
            )
        return inventory

    def _clear_transient_sso_cookies(self, session: requests.Session) -> list[str]:
        """Remove Keycloak cookies that belong to a completed authentication transaction.

        Persistent identity/session cookies are intentionally kept. Replaying stale
        AUTH_SESSION_ID/KC_AUTH_SESSION_HASH values can force Keycloak back into an
        old login transaction instead of reusing an existing SSO login.
        """
        removed: list[str] = []
        for cookie in list(session.cookies):
            if cookie.name not in TRANSIENT_SSO_COOKIE_NAMES:
                continue
            try:
                session.cookies.clear(cookie.domain, cookie.path, cookie.name)
                removed.append(cookie.name)
            except KeyError:
                continue
        return sorted(set(removed))

    def _try_sso_resume(self, session: requests.Session) -> PortalAuthResult | None:
        """Try to rebuild UPRX from cached SSO cookies without password or TOTP.

        UPRX's own JSESSIONID may not survive a client-process restart. Keycloak's
        SSO session can still be reusable, so re-enter through Shibboleth and follow
        only redirects/auto-post forms. If credentials or OTP are requested, stop
        immediately and let the normal interactive credential flow take over.
        """
        removed = self._clear_transient_sso_cookies(session)
        self._record_restore("sso-resume-start", removed_transient_cookies=removed)

        try:
            response = session.get(
                self.config.entry_url,
                timeout=self.config.timeout,
                allow_redirects=True,
            )
        except requests.RequestException as exc:
            self._record_restore("sso-resume-request-error", error=exc.__class__.__name__)
            raise

        soup = soup_from_response(response)
        followed_sso_entry = False
        portal_bridge_submitted = False
        portal_host = urlparse(self.config.app_base).netloc

        for step in range(self.config.max_auth_steps):
            parsed = urlparse(response.url)
            self.last_response = response
            self._record_restore(
                "sso-resume-step",
                step=step + 1,
                response_host=parsed.netloc,
                response_path=parsed.path,
                authenticated=self.is_authenticated(soup, response),
                has_sso_entry=bool(find_sso_entry_url(soup, response.url)),
                has_credentials=bool(find_credential_form(soup, response.url)),
                has_otp=bool(find_otp_form(soup, response.url)),
                has_auto_post=bool(find_auto_post_form(soup, response.url)),
            )

            if self.is_authenticated(soup, response):
                self._record_restore("restored-via-sso-session", response_path=parsed.path)
                self._save_session(session, response)
                return PortalAuthResult(session=session, response=response, soup=soup, restored=True)

            sso_entry = find_sso_entry_url(soup, response.url)
            if sso_entry and not followed_sso_entry:
                followed_sso_entry = True
                self._record_restore("sso-resume-follow-shibboleth-entry")
                try:
                    response = self._https_get(session, sso_entry, self.config.timeout)
                except requests.RequestException as exc:
                    self._record_restore("sso-resume-request-error", error=exc.__class__.__name__)
                    raise
                soup = soup_from_response(response)
                continue

            if find_credential_form(soup, response.url):
                self._record_restore("sso-resume-requires-credentials")
                return None

            if find_otp_form(soup, response.url):
                self._record_restore("sso-resume-requires-otp")
                return None

            if parsed.netloc == portal_host and parsed.path.endswith("/Pky00102.xhtml") and not portal_bridge_submitted:
                bridge_form = find_form_by_id(soup, response.url, "loginForm")
                if (
                    bridge_form is not None
                    and bridge_form.user_field is None
                    and bridge_form.password_field is None
                    and bridge_form.otp_field is None
                ):
                    portal_bridge_submitted = True
                    self._record_restore("sso-resume-submit-uprx-bridge-loginForm")
                    response = submit_form(session, bridge_form, {}, self.config.timeout)
                    soup = soup_from_response(response)
                    continue

            auto_post = find_auto_post_form(soup, response.url)
            if auto_post:
                self._record_restore("sso-resume-submit-auto-post-form")
                response = submit_form(session, auto_post, {}, self.config.timeout)
                soup = soup_from_response(response)
                continue

            redirect = find_client_redirect(soup, response.url)
            if redirect:
                self._record_restore("sso-resume-follow-client-redirect")
                try:
                    response = self._https_get(session, redirect, self.config.timeout)
                except requests.RequestException as exc:
                    self._record_restore("sso-resume-request-error", error=exc.__class__.__name__)
                    raise
                soup = soup_from_response(response)
                continue

            self._record_restore("sso-resume-stopped-unrecognized-page")
            return None

        self._record_restore("sso-resume-exceeded-max-steps")
        return None

    def _try_restore(self, session: requests.Session) -> PortalAuthResult | None:
        if not self.store.load(session):
            self._record_restore("cookie-cache-missing-or-invalid")
            return None

        self._record_restore(
            "cookie-cache-loaded",
            cookie_count=len(session.cookies),
            cookies=self._safe_cookie_inventory(session),
        )

        portal_host = urlparse(self.config.app_base).netloc

        for candidate in self._restore_candidate_urls():
            try:
                response = session.get(candidate, timeout=self.config.timeout, allow_redirects=True)
                soup = soup_from_response(response)
                self.last_response = response
                parsed = urlparse(response.url)
                self._record_restore(
                    "probe",
                    requested_path=urlparse(candidate).path,
                    response_host=parsed.netloc,
                    response_path=parsed.path,
                    authenticated=self.is_authenticated(soup, response),
                    has_sso_entry=bool(find_sso_entry_url(soup, response.url)),
                    has_credentials=bool(find_credential_form(soup, response.url)),
                    has_otp=bool(find_otp_form(soup, response.url)),
                    has_login_form=bool(find_form_by_id(soup, response.url, "loginForm")),
                )

                if self.is_authenticated(soup, response):
                    self._record_restore("restored-from-cookie-cache", response_path=parsed.path)
                    self._save_session(session, response)
                    return PortalAuthResult(session=session, response=response, soup=soup, restored=True)

                # The post-SAML bridge may still be returned when a valid cached
                # UPRX session exists. Replay only its hidden-only loginForm once;
                # never resend credentials or OTP during restoration.
                if (
                    parsed.netloc == portal_host
                    and parsed.path.endswith("/Pky00102.xhtml")
                    and find_credential_form(soup, response.url) is None
                    and find_otp_form(soup, response.url) is None
                ):
                    bridge_form = find_form_by_id(soup, response.url, "loginForm")
                    if (
                        bridge_form is not None
                        and bridge_form.user_field is None
                        and bridge_form.password_field is None
                        and bridge_form.otp_field is None
                    ):
                        self._record_restore("submit-uprx-bridge-loginForm")
                        bridge_response = submit_form(session, bridge_form, {}, self.config.timeout)
                        bridge_soup = soup_from_response(bridge_response)
                        self.last_response = bridge_response
                        bridge_parsed = urlparse(bridge_response.url)
                        self._record_restore(
                            "bridge-result",
                            response_host=bridge_parsed.netloc,
                            response_path=bridge_parsed.path,
                            authenticated=self.is_authenticated(bridge_soup, bridge_response),
                        )
                        if self.is_authenticated(bridge_soup, bridge_response):
                            self._save_session(session, bridge_response)
                            return PortalAuthResult(
                                session=session,
                                response=bridge_response,
                                soup=bridge_soup,
                                restored=True,
                            )

                        # Some UPRX deployments establish server state on the
                        # bridge postback but expose menuForm only on the normal
                        # Bsa00101 home URL. Probe it once before giving up.
                        home_response = session.get(
                            self.config.home_url,
                            timeout=self.config.timeout,
                            allow_redirects=True,
                        )
                        home_soup = soup_from_response(home_response)
                        self.last_response = home_response
                        home_parsed = urlparse(home_response.url)
                        self._record_restore(
                            "probe-home-after-bridge",
                            response_host=home_parsed.netloc,
                            response_path=home_parsed.path,
                            authenticated=self.is_authenticated(home_soup, home_response),
                        )
                        if self.is_authenticated(home_soup, home_response):
                            self._save_session(session, home_response)
                            return PortalAuthResult(
                                session=session,
                                response=home_response,
                                soup=home_soup,
                                restored=True,
                            )
            except requests.HTTPError as exc:
                # Expired UPRX sessions can respond 500 while the upstream SSO is
                # healthy. One passwordless SSO rebuild is safe; never resend
                # credentials merely because a service returned an error.
                if exc.response is not None and exc.response.status_code >= 500:
                    resumed = self._try_sso_resume(session)
                    if resumed is not None:
                        return resumed
                    if self.trace[-1].get("action") in {"sso-resume-requires-credentials", "sso-resume-requires-otp"}:
                        return None
                raise
            except requests.RequestException as exc:
                self._record_restore("probe-request-error", error=exc.__class__.__name__)
                raise

        # Direct UPRX cookie restoration can fail even while the upstream
        # Keycloak SSO login is still alive. Before discarding the cache, try a
        # passwordless/TOTP-less Shibboleth round-trip using the cached SSO cookies.
        sso_restored = self._try_sso_resume(session)
        if sso_restored is not None:
            return sso_restored

        self._record_restore("cookie-cache-rejected")
        self.store.clear()
        session.cookies.clear()
        return None

    def _record(self, step: int, response: requests.Response, soup: BeautifulSoup) -> None:
        self.last_response = response
        self.trace.append(
            {
                "step": step,
                "authenticated": self.is_authenticated(soup, response),
                "has_credentials": bool(find_credential_form(soup, response.url)),
                "has_otp": bool(find_otp_form(soup, response.url)),
            }
        )

    def _action(self, value: str) -> None:
        if self.trace:
            self.trace[-1]["action"] = value

    def login(self, force: bool = False) -> PortalAuthResult:
        with self._lock, session_lock(self.store.path.with_suffix(".lock")):
            self._attempt_session = None
            try:
                return self._login(force)
            except BaseException:
                if self._attempt_session is not None:
                    getattr(self._attempt_session, "close", lambda: None)()
                raise
            finally:
                self._attempt_session = None

    def _login(self, force: bool = False) -> PortalAuthResult:
        self.trace = []
        self.last_response = None
        session = self.new_session()
        self._attempt_session = session
        if not force:
            restored = self._try_restore(session)
            if restored:
                return restored

        creds = self.credentials_provider()
        response = session.get(self.config.entry_url, timeout=self.config.timeout, allow_redirects=True)
        soup = soup_from_response(response)

        credential_submitted = False
        otp_attempts = 0
        last_otp_counter: int | None = None
        followed_sso_entry = False
        portal_bridge_submitted = False
        portal_host = urlparse(self.config.app_base).netloc

        for step in range(self.config.max_auth_steps):
            self._record(step + 1, response, soup)

            if self.is_authenticated(soup, response):
                self._save_session(session, response)
                return PortalAuthResult(session=session, response=response, soup=soup)

            # The UPRX landing page contains both a legacy local-login form and the
            # student/staff SSO link. Always prefer Shibboleth SSO for this client.
            sso_entry = find_sso_entry_url(soup, response.url)
            if sso_entry and not followed_sso_entry:
                self._action("follow-shibboleth-sso-entry")
                followed_sso_entry = True
                response = self._https_get(session, sso_entry, self.config.timeout)
                soup = soup_from_response(response)
                continue

            credential_form = find_credential_form(soup, response.url)
            if credential_form:
                if credential_submitted:
                    raise AuthenticationError("Portal SSO rejected the credential submission.")
                user_field = self.config.user_field or credential_form.user_field
                password_field = self.config.password_field or credential_form.password_field
                if not user_field or not password_field:
                    raise AuthenticationError("Could not determine Portal credential field names.")
                credential_values = {
                    user_field: creds.user_id,
                    password_field: creds.password,
                }
                if self.config.remember_me_field and self.config.remember_me_field in credential_form.field_names:
                    credential_values[self.config.remember_me_field] = self.config.remember_me_value

                self._action("submit-sso-credentials")
                if self.trace and self.config.remember_me_field in credential_values:
                    self.trace[-1]["remember_me"] = True
                credential_submitted = True
                response = submit_form(
                    session,
                    credential_form,
                    credential_values,
                    self.config.timeout,
                    self.config.login_submit_field,
                )
                soup = soup_from_response(response)
                continue

            otp_form = find_otp_form(soup, response.url)
            if otp_form:
                max_attempts = max(1, self.config.totp_max_attempts)
                if otp_attempts >= max_attempts:
                    raise AuthenticationError("Portal rejected the bounded TOTP attempts.")
                if not creds.totp_secret:
                    raise MFARequired("Portal requested MFA; configure a TOTP credential in Keychain.")
                otp_field = self.config.otp_field or otp_form.otp_field
                if not otp_field:
                    raise AuthenticationError("Could not determine Portal OTP field name.")

                retrying = otp_attempts > 0
                code, timing, counter = self._prepare_totp(
                    creds.totp_secret,
                    response,
                    after_counter=last_otp_counter if retrying else None,
                )
                values = {otp_field: code}
                otp_credentials = find_otp_credentials(soup)
                selected_field = self.config.otp_credential_field
                if otp_credentials and selected_field:
                    credential_id = select_otp_credential_id(soup, self.config.totp_credential_label)
                    if credential_id:
                        values[selected_field] = credential_id
                    elif len(otp_credentials) > 1:
                        raise MFARequired("Configured TOTP credential label was not found; check Keychain setup.")

                self._action("retry-totp-next-window" if retrying else "submit-totp")
                if self.trace:
                    self.trace[-1].update(
                        {
                            "otp_attempt": otp_attempts + 1,
                            "totp_clock_source": timing.clock_source,
                            "server_clock_offset_seconds": round(timing.server_offset_seconds, 3),
                            "totp_remaining_seconds": round(timing.remaining_seconds, 3),
                            "totp_waited_seconds": round(timing.waited_seconds, 3),
                        }
                    )

                otp_attempts += 1
                last_otp_counter = counter
                response = submit_form(
                    session,
                    otp_form,
                    values,
                    self.config.timeout,
                    self.config.otp_submit_field,
                )
                soup = soup_from_response(response)
                continue

            parsed = urlparse(response.url)
            is_portal_uprx = parsed.netloc == portal_host and parsed.path.startswith("/uprx/")

            # After Keycloak + SAML, CIT currently lands on Pky00102.xhtml.
            # This page contains multiple hidden-only JSF forms (infoForm, errForm,
            # loginForm). Treating the first hidden-only form as an auto-submit form
            # causes an infinite loop. Probe the normal top page first, then submit
            # only loginForm once if the bridge still needs a JSF postback.
            if credential_submitted and otp_attempts > 0 and is_portal_uprx and parsed.path.endswith("/Pky00102.xhtml"):
                self._action("probe-uprx-top-after-saml")
                portal_response = session.get(self.config.top_url, timeout=self.config.timeout, allow_redirects=True)
                portal_soup = soup_from_response(portal_response)
                if self.is_authenticated(portal_soup, portal_response):
                    self._save_session(session, portal_response)
                    return PortalAuthResult(session=session, response=portal_response, soup=portal_soup)

                if not portal_bridge_submitted:
                    bridge_form = find_form_by_id(soup, response.url, "loginForm")
                    if bridge_form is not None:
                        self._action("submit-uprx-bridge-loginForm")
                        portal_bridge_submitted = True
                        response = submit_form(session, bridge_form, {}, self.config.timeout)
                        soup = soup_from_response(response)
                        continue

                raise AuthenticationError("Portal SSO bridge did not establish an authenticated menu.")

            auto_post = find_auto_post_form(soup, response.url)
            if auto_post:
                self._action("submit-auto-post-form")
                response = submit_form(session, auto_post, {}, self.config.timeout)
                soup = soup_from_response(response)
                continue

            redirect = find_client_redirect(soup, response.url)
            if redirect:
                self._action("follow-client-redirect")
                response = self._https_get(session, redirect, self.config.timeout)
                soup = soup_from_response(response)
                continue

            # SSO may have completed at Shibboleth without navigating to the UPRX top.
            if step > 0:
                portal_response = session.get(self.config.top_url, timeout=self.config.timeout, allow_redirects=True)
                portal_soup = soup_from_response(portal_response)
                if self.is_authenticated(portal_soup, portal_response):
                    self._save_session(session, portal_response)
                    return PortalAuthResult(session=session, response=portal_response, soup=portal_soup)

            raise AuthenticationError("Portal authentication requires additional interaction or has changed.")

        raise AuthenticationError("Portal authentication exceeded the maximum number of steps.")
