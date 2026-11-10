from unittest.mock import Mock

import pytest
import requests
from test_totp_timing import RetryLoginSession

from cit_campus_mcp.config import PortalConfig
from cit_campus_mcp.credentials import Credentials
from cit_campus_mcp.errors import AuthenticationError, MFARequired
from cit_campus_mcp.portal.auth import PortalAuthenticator
from cit_campus_mcp.session_store import CookieSessionStore


def test_mfa_required_without_seed(tmp_path):
    auth = PortalAuthenticator(credentials_provider=lambda: Credentials("synthetic", "synthetic"))
    auth.store = CookieSessionStore(tmp_path / "cache.json")
    auth.new_session = lambda: RetryLoginSession()
    with pytest.raises(MFARequired):
        auth.login(force=True)


def test_auth_failure_stops_credential_loop(tmp_path):
    session = RetryLoginSession()
    original = session.post
    credential_posts = []

    def reject(url, data=None, **kwargs):
        if "password" in (data or {}):
            credential_posts.append(1)
            return session.get("https://portal.chibatech.ac.jp/uprx/ShibbolethAuthServlet")
        return original(url, data=data, **kwargs)

    session.post = reject
    auth = PortalAuthenticator(credentials_provider=lambda: Credentials("synthetic", "synthetic"))
    auth.store = CookieSessionStore(tmp_path / "cache.json")
    auth.new_session = lambda: session
    with pytest.raises(AuthenticationError):
        auth.login(force=True)
    assert len(credential_posts) == 1


def test_login_loop_has_step_bound(tmp_path):
    session = requests.Session()
    r = requests.Response()
    r.status_code = 200
    r.url = "https://portal.chibatech.ac.jp/"
    r._content = b'<meta http-equiv="refresh" content="0;url=/">'
    session.get = Mock(return_value=r)
    auth = PortalAuthenticator(
        config=PortalConfig(max_auth_steps=3), credentials_provider=lambda: Credentials("synthetic", "synthetic")
    )
    auth.store = CookieSessionStore(tmp_path / "cache.json")
    auth.new_session = lambda: session
    with pytest.raises(AuthenticationError):
        auth.login(force=True)
    assert session.get.call_count == 4


def test_restore_500_rebuilds_sso_without_credentials(tmp_path):
    session = requests.Session()
    session.cookies.set("synthetic", "value")
    auth = PortalAuthenticator(credentials_provider=Mock(side_effect=AssertionError("must not read credentials")))
    auth.store = CookieSessionStore(tmp_path / "cache.json")
    auth.store.save(session)
    response = requests.Response()
    response.status_code = 500
    session.get = Mock(side_effect=requests.HTTPError(response=response))
    sentinel = object()
    auth._try_sso_resume = Mock(return_value=sentinel)
    assert auth._try_restore(session) is sentinel
    auth._try_sso_resume.assert_called_once_with(session)


def test_restore_503_does_not_force_credentials(tmp_path):
    session = requests.Session()
    session.cookies.set("synthetic", "value")
    provider = Mock(side_effect=AssertionError("must not read credentials"))
    auth = PortalAuthenticator(credentials_provider=provider)
    auth.store = CookieSessionStore(tmp_path / "cache.json")
    auth.store.save(session)
    r = requests.Response()
    r.status_code = 503
    session.get = Mock(side_effect=requests.HTTPError(response=r))
    auth._try_sso_resume = Mock(return_value=None)
    with pytest.raises(requests.HTTPError):
        auth._try_restore(session)
    provider.assert_not_called()
    assert auth.store.path.exists()
