import json

import requests

from cit_campus_mcp.portal.auth import PortalAuthenticator
from cit_campus_mcp.session_store import CookieSessionStore


class FakeSession:
    def __init__(self, *, home_menu=False, bridge_required=False):
        self.cookies = requests.cookies.RequestsCookieJar()
        self.requested = []
        self.posted = []
        self.home_menu = home_menu
        self.bridge_required = bridge_required
        self.headers = {}

    def get(self, url, timeout=None, allow_redirects=True):
        self.requested.append(url)
        response = requests.Response()
        response.status_code = 200
        response.url = url
        if url.endswith("/Bsa00101.xhtml") and self.home_menu:
            response._content = b'<html><body><form id="menuForm"></form></body></html>'
        elif url.endswith("/Pky00102.xhtml") and self.bridge_required:
            response._content = b"""<html><body>
              <form id="infoForm" method="post" action="/uprx/up/pk/pky001/Pky00102.xhtml">
                <input type="hidden" name="infoForm" value="infoForm">
                <input type="hidden" name="javax.faces.ViewState" value="stateless">
              </form>
              <form id="loginForm" method="post" action="/uprx/up/pk/pky001/Pky00102.xhtml">
                <input type="hidden" name="loginForm" value="loginForm">
                <input type="hidden" name="javax.faces.ViewState" value="stateless">
              </form>
            </body></html>"""
        else:
            response._content = b'<html><body><form id="loginForm"></form></body></html>'
        response.encoding = "utf-8"
        return response

    def post(self, url, data=None, timeout=None, allow_redirects=True):
        self.posted.append((url, dict(data or {})))
        response = requests.Response()
        response.status_code = 200
        response.url = url
        if self.bridge_required and url.endswith("/Pky00102.xhtml") and "loginForm" in (data or {}):
            response._content = b'<html><body><form id="menuForm"></form></body></html>'
        else:
            response._content = b'<html><body><form id="loginForm"></form></body></html>'
        response.encoding = "utf-8"
        return response


def _write_cookie_file(path, metadata=None):
    payload = {
        "version": 2,
        "cookies": [
            {
                "name": "JSESSIONID",
                "value": "test-session",
                "domain": "portal.chibatech.ac.jp",
                "path": "/uprx",
                "secure": True,
                "expires": None,
            }
        ],
    }
    if metadata:
        payload["metadata"] = metadata
    path.write_text(json.dumps(payload), encoding="utf-8")
    path.chmod(0o600)


def _auth_with_store(path):
    auth = PortalAuthenticator(
        credentials_provider=lambda: (_ for _ in ()).throw(AssertionError("credentials should not be requested"))
    )
    auth.store = CookieSessionStore(path)
    return auth


def test_restore_probes_real_application_home_first(tmp_path):
    path = tmp_path / "portal-session.json"
    _write_cookie_file(path)
    auth = _auth_with_store(path)
    session = FakeSession(home_menu=True)

    result = auth._try_restore(session)

    assert result is not None
    assert result.restored is True
    assert session.requested[0].endswith("/uprx/up/bs/bsa001/Bsa00101.xhtml")
    assert any(e.get("action") == "restored-from-cookie-cache" for e in auth.trace)


def test_restore_falls_back_to_pky_bridge_for_old_cache(tmp_path):
    path = tmp_path / "portal-session.json"
    _write_cookie_file(path)
    auth = _auth_with_store(path)
    session = FakeSession(bridge_required=True)

    result = auth._try_restore(session)

    assert result is not None
    assert result.restored is True
    assert len(session.posted) == 1
    url, data = session.posted[0]
    assert url.endswith("/Pky00102.xhtml")
    assert data["loginForm"] == "loginForm"


def test_saved_last_authenticated_url_does_not_override_home_probe(tmp_path):
    path = tmp_path / "portal-session.json"
    _write_cookie_file(
        path,
        metadata={"last_authenticated_url": "https://portal.chibatech.ac.jp/uprx/up/pk/pky001/Pky00102.xhtml"},
    )
    auth = _auth_with_store(path)
    assert auth._restore_candidate_urls()[0].endswith("/uprx/up/bs/bsa001/Bsa00101.xhtml")


def test_restore_trace_never_contains_cookie_values(tmp_path):
    path = tmp_path / "portal-session.json"
    _write_cookie_file(path)
    auth = _auth_with_store(path)
    session = FakeSession(home_menu=True)

    result = auth._try_restore(session)
    assert result is not None

    trace_text = json.dumps(auth.trace)
    assert "test-session" not in trace_text
    assert "JSESSIONID" not in trace_text


def test_transient_keycloak_auth_cookies_are_removed_but_sso_cookies_remain(tmp_path):
    auth = _auth_with_store(tmp_path / "unused.json")
    session = requests.Session()
    session.cookies.set("AUTH_SESSION_ID", "old-auth", domain="sso.chibatech.ac.jp", path="/realms/marine/")
    session.cookies.set("KC_AUTH_SESSION_HASH", "old-hash", domain="sso.chibatech.ac.jp", path="/realms/marine/")
    session.cookies.set("KEYCLOAK_IDENTITY", "identity", domain="sso.chibatech.ac.jp", path="/realms/marine/")
    session.cookies.set("KEYCLOAK_SESSION", "session", domain="sso.chibatech.ac.jp", path="/realms/marine/")

    removed = auth._clear_transient_sso_cookies(session)
    names = {cookie.name for cookie in session.cookies}

    assert removed == ["AUTH_SESSION_ID", "KC_AUTH_SESSION_HASH"]
    assert "AUTH_SESSION_ID" not in names
    assert "KC_AUTH_SESSION_HASH" not in names
    assert "KEYCLOAK_IDENTITY" in names
    assert "KEYCLOAK_SESSION" in names


class FakeSsoResumeSession:
    def __init__(self):
        self.cookies = requests.cookies.RequestsCookieJar()
        self.headers = {}
        self.cookies.set("AUTH_SESSION_ID", "stale", domain="sso.chibatech.ac.jp", path="/realms/marine/")
        self.cookies.set("KEYCLOAK_IDENTITY", "identity", domain="sso.chibatech.ac.jp", path="/realms/marine/")
        self.cookies.set("KEYCLOAK_SESSION", "session", domain="sso.chibatech.ac.jp", path="/realms/marine/")

    @staticmethod
    def _response(url, html):
        response = requests.Response()
        response.status_code = 200
        response.url = url
        response._content = html.encode("utf-8")
        response.encoding = "utf-8"
        return response

    def get(self, url, timeout=None, allow_redirects=True):
        if url == "https://portal.chibatech.ac.jp/":
            return self._response(url, '<script>window.location.href="/uprx/";</script>')
        if url == "https://portal.chibatech.ac.jp/uprx/":
            return self._response(
                url,
                """
                <a href="https://portal.chibatech.ac.jp/uprx/ShibbolethAuthServlet">在学生・教職員専用ログイン（統合認証）</a>
            """,
            )
        if url.endswith("/uprx/ShibbolethAuthServlet"):
            return self._response(
                "https://sso.chibatech.ac.jp/realms/marine/protocol/saml",
                """<form action="https://portal.chibatech.ac.jp/uprx/ShibbolethAuthServlet" method="post">
                     <input type="hidden" name="SAMLResponse" value="opaque">
                     <input type="hidden" name="RelayState" value="opaque">
                   </form>""",
            )
        raise AssertionError(f"unexpected GET {url}")

    def post(self, url, data=None, timeout=None, allow_redirects=True):
        if url.endswith("/uprx/ShibbolethAuthServlet") and "SAMLResponse" in (data or {}):
            return self._response(
                "https://portal.chibatech.ac.jp/uprx/ShibbolethAuthServlet",
                """<form action="https://portal.chibatech.ac.jp/uprx/up/pk/pky001/Pky00102.xhtml" method="post">
                     <input type="hidden" name="SAMLResponse" value="opaque2">
                     <input type="hidden" name="RelayState" value="opaque2">
                   </form>""",
            )
        if url.endswith("/Pky00102.xhtml") and "SAMLResponse" in (data or {}):
            return self._response(
                "https://portal.chibatech.ac.jp/uprx/up/pk/pky001/Pky00102.xhtml",
                """<form id="loginForm" action="/uprx/up/pk/pky001/Pky00102.xhtml" method="post">
                     <input type="hidden" name="loginForm" value="loginForm">
                     <input type="hidden" name="javax.faces.ViewState" value="stateless">
                   </form>""",
            )
        if url.endswith("/Pky00102.xhtml") and "loginForm" in (data or {}):
            return self._response(
                "https://portal.chibatech.ac.jp/uprx/up/pk/pky001/Pky00102.xhtml",
                '<form id="menuForm"></form>',
            )
        raise AssertionError(f"unexpected POST {url} {data}")


def test_sso_resume_rebuilds_portal_without_credentials_or_otp(tmp_path):
    auth = _auth_with_store(tmp_path / "unused.json")
    session = FakeSsoResumeSession()

    result = auth._try_sso_resume(session)

    assert result is not None
    assert result.restored is True
    assert any(e.get("action") == "restored-via-sso-session" for e in auth.trace)
    names = {cookie.name for cookie in session.cookies}
    assert "AUTH_SESSION_ID" not in names
    assert "KEYCLOAK_IDENTITY" in names
    assert "KEYCLOAK_SESSION" in names
