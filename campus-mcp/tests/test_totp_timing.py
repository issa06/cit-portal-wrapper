import json
from datetime import datetime, timezone
from email.utils import format_datetime

import requests

from cit_campus_mcp.config import PortalConfig
from cit_campus_mcp.credentials import Credentials
from cit_campus_mcp.portal.auth import PortalAuthenticator
from cit_campus_mcp.session_store import CookieSessionStore
from cit_campus_mcp.totp import generate_totp

SECRET = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"


class FakeClock:
    def __init__(self, now: float):
        self.now = now
        self.sleeps: list[float] = []

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def _response_with_server_time(timestamp: float) -> requests.Response:
    response = requests.Response()
    response.status_code = 200
    response.url = "https://sso.chibatech.ac.jp/realms/marine/login-actions/authenticate"
    response.headers["Date"] = format_datetime(
        datetime.fromtimestamp(timestamp, tz=timezone.utc),
        usegmt=True,
    )
    response._content = b""
    return response


def test_totp_uses_server_date_and_waits_when_code_is_about_to_expire(tmp_path):
    # Local clock is 30 seconds behind the SSO server. The server is also one
    # second away from the TOTP rollover, so r1.7 must wait for the next window.
    clock = FakeClock(29.0)
    config = PortalConfig(
        totp_interval=30,
        totp_digits=8,
        totp_algorithm="SHA1",
        totp_min_validity_seconds=5.0,
        totp_rollover_guard_seconds=0.25,
    )
    auth = PortalAuthenticator(
        config=config,
        credentials_provider=lambda: None,  # Not used by this unit test.
        clock=clock.time,
        sleeper=clock.sleep,
    )
    response = _response_with_server_time(59.0)

    code, timing, counter = auth._prepare_totp(SECRET, response)

    assert timing.clock_source == "http-date"
    assert round(timing.server_offset_seconds, 3) == 30.0
    assert round(timing.waited_seconds, 3) == 1.25
    assert round(timing.remaining_seconds, 3) == 29.75
    assert counter == 2
    assert code == generate_totp(
        SECRET,
        timestamp=60.25,
        digits=8,
        interval=30,
        algorithm="SHA1",
    )


def test_totp_retry_waits_until_a_new_counter_window():
    clock = FakeClock(100.0)
    config = PortalConfig(
        totp_interval=30,
        totp_min_validity_seconds=5.0,
        totp_rollover_guard_seconds=0.25,
    )
    auth = PortalAuthenticator(
        config=config,
        credentials_provider=lambda: None,
        clock=clock.time,
        sleeper=clock.sleep,
    )
    response = requests.Response()
    response.status_code = 200
    response.url = "https://sso.chibatech.ac.jp/realms/marine/login-actions/authenticate"

    _, timing, counter = auth._prepare_totp(SECRET, response, after_counter=3)

    assert timing.clock_source == "local"
    assert round(timing.waited_seconds, 3) == 20.25
    assert counter == 4
    assert round(timing.remaining_seconds, 3) == 29.75


def test_totp_does_not_wait_when_enough_validity_remains():
    clock = FakeClock(42.0)
    config = PortalConfig(
        totp_interval=30,
        totp_min_validity_seconds=5.0,
        totp_rollover_guard_seconds=0.25,
    )
    auth = PortalAuthenticator(
        config=config,
        credentials_provider=lambda: None,
        clock=clock.time,
        sleeper=clock.sleep,
    )
    response = requests.Response()
    response.status_code = 200
    response.url = "https://sso.chibatech.ac.jp/realms/marine/login-actions/authenticate"

    _, timing, counter = auth._prepare_totp(SECRET, response)

    assert clock.sleeps == []
    assert timing.waited_seconds == 0.0
    assert counter == 1
    assert timing.remaining_seconds == 18.0


class RetryLoginSession:
    def __init__(self):
        self.cookies = requests.cookies.RequestsCookieJar()
        self.headers: dict[str, str] = {}
        self.otp_values: list[str] = []

    @staticmethod
    def _response(url: str, html: str) -> requests.Response:
        response = requests.Response()
        response.status_code = 200
        response.url = url
        response._content = html.encode("utf-8")
        response.encoding = "utf-8"
        return response

    def get(self, url, timeout=None, allow_redirects=True):
        if url == "https://portal.chibatech.ac.jp/":
            return self._response(
                url,
                '<a href="https://portal.chibatech.ac.jp/uprx/ShibbolethAuthServlet">統合認証</a>',
            )
        if url.endswith("/uprx/ShibbolethAuthServlet"):
            return self._response(
                "https://sso.chibatech.ac.jp/realms/marine/login-actions/authenticate",
                """
                <form action="https://sso.chibatech.ac.jp/realms/marine/login-actions/authenticate" method="post">
                  <input name="username" type="text">
                  <input name="password" type="password">
                  <button name="login" type="submit">Sign In</button>
                </form>
                """,
            )
        raise AssertionError(f"unexpected GET {url}")

    def post(self, url, data=None, timeout=None, allow_redirects=True):
        data = data or {}
        if "password" in data:
            return self._response(
                url,
                """
                <form action="https://sso.chibatech.ac.jp/realms/marine/login-actions/authenticate" method="post">
                  <input name="selectedCredentialId" type="hidden" value="python-id">
                  <div id="kc-otp-credential-0" onclick="toggleOTP(0, 'python-id')">
                    <span class="pf-v5-c-tile__title">Python</span>
                  </div>
                  <input name="otp" type="text" autocomplete="one-time-code">
                  <button name="login" type="submit">Sign In</button>
                </form>
                """,
            )
        if "otp" in data:
            self.otp_values.append(data["otp"])
            if len(self.otp_values) == 1:
                return self._response(
                    url,
                    """
                    <div role="alert">Invalid authenticator code.</div>
                    <form action="https://sso.chibatech.ac.jp/realms/marine/login-actions/authenticate" method="post">
                      <input name="selectedCredentialId" type="hidden" value="python-id">
                      <div id="kc-otp-credential-0" onclick="toggleOTP(0, 'python-id')">
                        <span class="pf-v5-c-tile__title">Python</span>
                      </div>
                      <input name="otp" type="text" autocomplete="one-time-code">
                      <button name="login" type="submit">Sign In</button>
                    </form>
                    """,
                )
            return self._response(
                "https://portal.chibatech.ac.jp/uprx/up/bs/bsa001/Bsa00101.xhtml",
                '<form id="menuForm"></form>',
            )
        raise AssertionError(f"unexpected POST {url} {data}")


def test_login_retries_otp_once_with_a_new_time_window(tmp_path):
    clock = FakeClock(100.0)
    session = RetryLoginSession()
    config = PortalConfig(
        totp_interval=30,
        totp_min_validity_seconds=5.0,
        totp_rollover_guard_seconds=0.25,
        totp_max_attempts=2,
    )
    auth = PortalAuthenticator(
        config=config,
        credentials_provider=lambda: Credentials(
            user_id="student",
            password="password",
            totp_secret=SECRET,
        ),
        clock=clock.time,
        sleeper=clock.sleep,
    )
    auth.store = CookieSessionStore(tmp_path / "portal-session.json")
    auth.new_session = lambda: session

    result = auth.login(force=True)

    assert result.response.url.endswith("/Bsa00101.xhtml")
    assert len(session.otp_values) == 2
    assert session.otp_values[0] != session.otp_values[1]
    assert any(entry.get("action") == "retry-totp-next-window" for entry in auth.trace)
    retry_trace = next(entry for entry in auth.trace if entry.get("action") == "retry-totp-next-window")
    assert retry_trace["otp_attempt"] == 2
    assert retry_trace["totp_waited_seconds"] == 20.25
    trace_text = json.dumps(auth.trace)
    assert SECRET not in trace_text
    assert session.otp_values[0] not in trace_text
    assert session.otp_values[1] not in trace_text
