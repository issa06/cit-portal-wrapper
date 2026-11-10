import json
import stat
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import Mock

import anyio
import pytest
import requests
from bs4 import BeautifulSoup

from cit_campus_mcp.config import PortalConfig
from cit_campus_mcp.credentials import Credentials, portal_credentials
from cit_campus_mcp.errors import (
    AuthenticationError,
    DataUnavailable,
    MFARequired,
    SessionExpired,
    StructureChanged,
    public_error,
)
from cit_campus_mcp.http import SafeSession
from cit_campus_mcp.portal.auth import PortalAuthenticator
from cit_campus_mcp.portal.client import PortalClient
from cit_campus_mcp.portal.parsers import _parse_attendance_table, get_grades, get_notices, parse_notices
from cit_campus_mcp.session_store import CookieSessionStore, session_lock
from cit_campus_mcp.tooling import safe_tool
from cit_campus_mcp.webforms import portal_page


def soup(markup):
    return BeautifulSoup(markup, "lxml")


def response(markup, status=200):
    r = requests.Response()
    r.status_code = status
    r.url = "https://portal.chibatech.ac.jp/uprx/"
    r._content = markup.encode()
    r.encoding = "utf-8"
    return r


def test_unlogged_missing_credentials(monkeypatch):
    monkeypatch.setattr("cit_campus_mcp.credentials._get", lambda *args: None)
    with pytest.raises(AuthenticationError):
        portal_credentials()


def test_totp_optional_until_mfa_requested(monkeypatch):
    monkeypatch.setattr(
        "cit_campus_mcp.credentials._get", lambda account, env: None if "totp" in account else "synthetic"
    )
    assert portal_credentials().totp_secret is None


def test_credentials_repr_is_private():
    assert "synthetic-secret" not in repr(Credentials("synthetic-id", "synthetic-secret", "synthetic-seed"))


def test_expired_page_is_not_empty():
    with pytest.raises(SessionExpired):
        portal_page(response('<form><input type="password" name="password"></form>'))


def test_partial_cdata_and_view_state():
    page = portal_page(
        response("""<partial-response><changes><update id="funcForm"><![CDATA[
        <form id="funcForm"><input name="javax.faces.ViewState" value="old"><div id="keiji"><a>Test</a></div></form>
        ]]></update><update id="javax.faces.ViewState"><![CDATA[new]]></update></changes></partial-response>""")
    )
    assert page.select_one("#keiji a").get_text() == "Test"
    assert page.select_one("input")["value"] == "new"


def test_empty_notice_and_changed_html_differ():
    assert parse_notices(soup("<p>掲示はありません</p>")) == []
    with pytest.raises(StructureChanged):
        parse_notices(soup("<p>Unexpected page</p>"))


def test_notice_flags_are_unknown_when_not_supplied():
    row = parse_notices(soup('<div id="keiji"><a>ＡＢＣ</a>2026/11/1</div>'))[0]
    assert row["title"] == "ABC"
    assert row["date"] == "2026-11-01"
    assert row["important"] is None and row["unread_or_highlighted"] is None


def test_multiple_pages_deduplicate():
    first = soup("""<form id="funcForm"><input type="hidden" name="state" value="one"></form>
        <div id="keiji"><a>one</a>2026/11/1</div><button title="次へ" id="next"></button>""")
    second = response("""<div id="keiji"><a>one</a>2026/11/1</div><div id="keiji"><a>two</a>2026/11/2</div>""")
    top = SimpleNamespace(
        menu_post=lambda _: first, config=PortalConfig(), session=SimpleNamespace(post=Mock(return_value=second))
    )
    assert len(get_notices(top, full=True)) == 2
    assert top.session.post.call_count == 1


def test_repeated_notice_page_is_failure():
    markup = '<div id="keiji"><a>one</a></div><button title="次へ" id="next"></button>'
    top = SimpleNamespace(
        menu_post=lambda _: soup(markup),
        config=PortalConfig(),
        session=SimpleNamespace(post=Mock(return_value=response(markup))),
    )
    with pytest.raises(StructureChanged):
        get_notices(top, full=True)


def test_attendance_missing_status_and_unknown_status():
    rows = _parse_attendance_table(
        soup("""<div class="attendanceInfo"><table><tbody><tr>
        <td>月1</td><td>123Test（Teacher）</td><td></td><td><span class="syuketsuKbnMark">?</span></td>
        <td><span class="syuketsuKbnMark">公欠</span></td></tr></tbody></table></div>""")
    )
    assert rows[0]["missing_status_count"] == 2
    assert rows[0]["computed_summary"]["excused"] == 1
    assert rows[0]["summary_source"] == "local_record_count"


def test_unpublished_grades_and_changed_html_differ():
    with pytest.raises(DataUnavailable):
        get_grades(SimpleNamespace(menu_post=lambda _: soup("<p>成績は未公開</p>")))
    with pytest.raises(StructureChanged):
        get_grades(SimpleNamespace(menu_post=lambda _: soup("<p>unexpected</p>")))


def test_dynamic_grade_ids_and_blank_evaluation():
    rows = get_grades(
        SimpleNamespace(
            menu_post=lambda _: soup("""<div id="funcForm:dynamic:3:sskList"><table><tbody>
        <tr><td>1</td><td>Test</td><td>2</td><td></td><td></td><td></td><td>Teacher</td></tr>
        </tbody></table></div>""")
        )
    )
    assert rows[0]["evaluation"] is None
    assert rows[0]["gpa_target"] is None
    assert rows[0]["publication_status"] == "unpublished"


@pytest.mark.parametrize(
    "exc,code",
    [
        (requests.Timeout("sensitive-url"), "TIMEOUT"),
        (requests.ConnectionError("secret-token"), "NETWORK_ERROR"),
        (MFARequired("seed"), "MFA_REQUIRED"),
        (AuthenticationError("password"), "AUTHENTICATION_FAILED"),
    ],
)
def test_public_errors_never_echo_values(exc, code):
    assert public_error(exc)["code"] == code
    assert str(exc) not in json.dumps(public_error(exc))


@pytest.mark.parametrize("status,code", [(429, "RATE_LIMITED"), (503, "SERVICE_UNAVAILABLE"), (401, "SESSION_EXPIRED")])
def test_http_error_classification(status, code):
    assert public_error(requests.HTTPError("sensitive", response=response("", status)))["code"] == code


@pytest.mark.parametrize(
    "url",
    [
        "http://portal.chibatech.ac.jp/",
        "https://evil.invalid/",
        "https://user:secret@portal.chibatech.ac.jp/",
        "https://portal.chibatech.ac.jp:444/",
    ],
)
def test_host_guard_before_network(url):
    with pytest.raises(AuthenticationError):
        SafeSession({"portal.chibatech.ac.jp"}).get(url)


def test_redirect_guard_checks_target():
    r = response("", 302)
    r.headers["Location"] = "https://evil.invalid/"
    with pytest.raises(AuthenticationError):
        SafeSession({"portal.chibatech.ac.jp"}).get_redirect_target(r)


def test_auth_post_not_in_retry_methods():
    retries = SafeSession({"portal.chibatech.ac.jp"}).get_adapter("https://").max_retries
    assert "POST" not in retries.allowed_methods
    assert retries.total == 1
    assert retries.connect == 0
    assert retries.increment(method="GET", error=None).get_backoff_time() >= 0.5


def test_store_restarts_atomic_private_and_corrupt_safe(tmp_path):
    path = tmp_path / "cache.json"
    store = CookieSessionStore(path)
    first = requests.Session()
    first.cookies.set("synthetic", "secret", domain="portal.chibatech.ac.jp")
    store.save(first)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    second = requests.Session()
    assert CookieSessionStore(path).load(second)
    assert second.cookies.get("synthetic") == "secret"
    path.write_text('{"cookies":[{"name":"partial","value":"x"},{}]}')
    third = requests.Session()
    assert not store.load(third)
    assert not third.cookies


def test_unsafe_cache_permissions_rejected(tmp_path):
    path = tmp_path / "cache.json"
    path.write_text('{"cookies":[{"name":"x","value":"secret"}]}')
    path.chmod(0o644)
    assert not CookieSessionStore(path).load(requests.Session())


def test_cross_process_lock_timeout(tmp_path):
    from cit_campus_mcp.errors import RequestTimeout

    path = tmp_path / "lock"
    with session_lock(path):
        with pytest.raises(RequestTimeout), session_lock(path, timeout=0):
            pass


def client_for_test(tmp_path):
    auth = SimpleNamespace(store=CookieSessionStore(tmp_path / "cache.json"))
    client = PortalClient(authenticator=auth)
    client.connect = Mock(return_value=object())
    return client


def test_concurrent_operations_share_cache(tmp_path):
    client = client_for_test(tmp_path)
    calls = []

    def fetch(top):
        calls.append(1)
        time.sleep(0.01)
        return [{"synthetic": True}]

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda _: client.run("same", fetch), range(6)))
    assert len(calls) == 1
    results[0][0]["synthetic"] = False
    assert client.run("same", fetch)[0]["synthetic"] is True


def test_cache_expiry_and_explicit_refresh(tmp_path):
    client = client_for_test(tmp_path)
    now = [0]
    client.clock = lambda: now[0]
    fetch = Mock(return_value=[])
    client.run("same", fetch)
    client.run("same", fetch)
    assert fetch.call_count == 1
    now[0] = 31
    client.run("same", fetch)
    client.run("same", fetch, refresh=True)
    assert fetch.call_count == 3


def test_session_expiry_recovered_once(tmp_path):
    client = client_for_test(tmp_path)
    parser = Mock(side_effect=[SessionExpired(), []])
    assert client.run("same", parser) == []
    assert parser.call_count == 2
    parser = Mock(side_effect=SessionExpired())
    with pytest.raises(SessionExpired):
        client.run("other", parser)
    assert parser.call_count == 2


@pytest.mark.parametrize("failure", [requests.Timeout, requests.ConnectionError])
def test_transport_failure_not_retried_as_login(tmp_path, failure):
    client = client_for_test(tmp_path)
    parser = Mock(side_effect=failure("private-url"))
    with pytest.raises(failure):
        client.run("same", parser)
    assert parser.call_count == 1
    assert not client.cache


def test_tool_error_and_size_limit():
    @safe_tool
    def failing():
        raise RuntimeError("private-student-data")

    @safe_tool
    def oversized():
        return {"text": "x" * 150000}

    async def check():
        result = await failing()
        assert result.is_error and result.structured_content["error"]["code"] == "INTERNAL_ERROR"
        assert "private-student-data" not in result.model_dump_json()
        result = await oversized()
        assert result.is_error and result.structured_content["error"]["code"] == "RESPONSE_TOO_LARGE"

    anyio.run(check)


def test_cancel_does_not_block_mcp_loop():
    @safe_tool
    def slow():
        time.sleep(0.15)
        return []

    async def check():
        start = time.monotonic()
        with anyio.move_on_after(0.02) as scope:
            await slow()
        assert scope.cancel_called and time.monotonic() - start < 0.12

    anyio.run(check)


def test_restore_network_outage_retains_cache(tmp_path):
    store = CookieSessionStore(tmp_path / "cache.json")
    session = requests.Session()
    session.cookies.set("synthetic", "value")
    store.save(session)
    auth = PortalAuthenticator(credentials_provider=Mock(side_effect=AssertionError("must not use credentials")))
    auth.store = store
    session.get = Mock(side_effect=requests.Timeout("private-url"))
    with pytest.raises(requests.Timeout):
        auth._try_restore(session)
    assert store.path.exists()


def test_in_memory_session_does_not_probe_home_or_reauthenticate(tmp_path):
    from cit_campus_mcp.portal.auth import PortalAuthResult

    r = response(
        '<form id="menuForm" action="/uprx/current.xhtml"><input type="hidden" name="state" value="new"></form>'
    )
    session = requests.Session()
    session.get = Mock(side_effect=AssertionError("unnecessary home probe"))
    session.post = Mock(return_value=r)
    auth = PortalAuthenticator()
    auth.store = CookieSessionStore(tmp_path / "cache.json")
    auth.login = Mock(return_value=PortalAuthResult(session, r, soup(r.text)))
    client = PortalClient(auth)
    for key in ["notices", "grades", "attendance"]:
        client.run(key, lambda top: top.menu_post("synthetic-menu").get_text())
    assert auth.login.call_count == 1
    assert session.get.call_count == 0
    assert session.post.call_count == 3
    assert session.post.call_args.args[0] == "https://portal.chibatech.ac.jp/uprx/current.xhtml"
