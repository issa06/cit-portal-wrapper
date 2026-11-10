from pathlib import Path

import pytest
import requests
from bs4 import BeautifulSoup

from cit_campus_mcp.config import PortalConfig
from cit_campus_mcp.errors import (
    NoticeAmbiguous,
    NoticeNotFound,
    ReadStateChangeRequired,
    ReadStateUnknown,
    ReadStateVerificationFailed,
    StructureChanged,
)
from cit_campus_mcp.portal.auth import PortalAuthResult
from cit_campus_mcp.portal.client import PortalClient
from cit_campus_mcp.portal.notices import fetch_notice, notice_read_state
from cit_campus_mcp.portal.parsers import parse_notices
from cit_campus_mcp.session_store import CookieSessionStore

SOURCE = "funcForm:tabArea:0:j_idt1:0:j_idt2:0:j_idt3"
ATTACH = "bsd001001:ch:j_idt10"
PREPARE = "pkx001001:ch:appendList:0:j_idt20"
DOWNLOAD = "pkx001001:ch:appendList:0:j_idt21"


def handler(source):
    return f'PrimeFaces.ab({{s:"{source}",p:"{source}"}});return false;'


def listing(state="read", duplicate=False):
    classes = "ui-commandlink ui-widget" + (
        " fontBold" if state == "unread" else " changed-renderer" if state == "unknown" else ""
    )
    card = f'''<dl id="keiji" class="keiji"><i class="fa-lightbulb-o"></i><span class="keijiCategory">Test</span>
    <a id="{SOURCE}" class="{classes}" onclick='{handler(SOURCE)}'>Synthetic notice</a>2026/11/10</dl>'''
    return f"""<form id="menuForm" action="/uprx/list.xhtml"></form>
    <form id="funcForm" action="/uprx/list.xhtml"><input type="hidden" name="javax.faces.ViewState" value="before">
    {card}{card if duplicate else ""}</form>
    <form id="bsd001001" action="/uprx/list.xhtml"><input type="hidden" name="javax.faces.ViewState" value="before"><div id="bsd001001:dialogPanel"></div></form>
    <form id="pkx001001" action="/uprx/list.xhtml"><input type="hidden" name="javax.faces.ViewState" value="before"></form>"""


def partial(identity, markup, state="after"):
    return f'''<partial-response><changes><update id="{identity}"><![CDATA[{markup}]]></update>
    <update id="j_id1:javax.faces.ViewState:0"><![CDATA[{state}]]></update></changes>
    <eval><![CDATA[neverExecuteOrMarkRead();]]></eval></partial-response>'''


def detail(attachments=True, missing_body=False):
    return f'''<div id="bsd001001:dialogPanel"><form id="bsd001001:ch" action="/uprx/list.xhtml"><input type="hidden" name="javax.faces.ViewState" value="before"><table class="ui-panelgrid"><tbody>
    <tr><td class="ui-widget-header">差出人</td><td>Synthetic office</td></tr>
    {"" if missing_body else '<tr><td class="ui-widget-header">本文</td><td class="contents"><div class="fr-view"><p>One <span>inline</span> phrase</p><p>Second<br>line</p><script>private-script</script></div></td></tr>'}
    </tbody></table><button id="{ATTACH}" onclick='{handler(ATTACH)}' {'disabled="disabled"' if not attachments else ""}>添付資料</button></form></div>'''


PREPARE_HANDLER = handler(PREPARE).replace(
    "});return false;",
    ',onco:function(xhr,status,args){if(!args.exceptionFlg){PF("download_widget").getJQ().click();}}});return false;',
)
FILES = f'''<div id="pkx001001:dialogPanel"><form id="pkx001001:ch" action="/uprx/list.xhtml"><input type="hidden" name="javax.faces.ViewState" value="before"><div><button id="{PREPARE}" onclick='{PREPARE_HANDLER}'><span class="ui-button-text">synthetic.pdf</span></button>
<button id="{DOWNLOAD}" name="{DOWNLOAD}" type="submit" onclick='this.form.target="";'>Download</button>
<script>PrimeFaces.cw("CommandButton","download_widget",{{id:"{DOWNLOAD}"}});</script></div></form></div>'''


def response(content, mime="text/html"):
    r = requests.Response()
    r.status_code = 200
    r.url = "https://portal.chibatech.ac.jp/uprx/list.xhtml"
    r._content = content.encode() if isinstance(content, str) else content
    r.headers["Content-Type"] = mime
    return r


class Session:
    def __init__(self, app, index):
        self.app, self.index, self.prepared = app, index, False
        self.closed = False

    def close(self):
        self.closed = True

    def post(self, url, data, **kwargs):
        if data.get("rx.sync.source"):
            self.app.events.append("list")
            state = self.app.state if self.index == 0 else self.app.after_state
            return response(listing(state, self.app.duplicate))
        source = data.get("javax.faces.source")
        if source == SOURCE:
            self.app.events.append("detail")
            assert self.app.state == "read", "Unread detail must never be selected"
            if self.app.failure:
                raise self.app.failure
            return response(partial("bsd001001:dialogPanel", detail(self.app.attachments, self.app.missing_body)))
        if source == ATTACH:
            self.app.events.append("attachments")
            assert data["javax.faces.ViewState"] == "after"
            return response(partial("pkx001001:dialogPanel", self.app.files_markup))
        if source == PREPARE:
            self.app.events.append("prepare")
            self.prepared = True
            flag = "true" if self.app.prepare_exception else "false"
            markup = partial("unused", "").replace(
                "</partial-response>",
                '<extension type="args">{"exceptionFlg":' + flag + "}</extension></partial-response>",
            )
            if self.app.omit_callback_args:
                markup = partial("unused", "")
            return response(markup)
        if DOWNLOAD in data:
            self.app.events.append("download")
            assert self.prepared
            if self.app.download_html:
                return response("<p>error</p>", "text/html")
            return response(b"%PDF-synthetic-only", "application/pdf")
        raise AssertionError("Unexpected request")


class App:
    def __init__(
        self,
        tmp_path,
        state="read",
        after_state=None,
        attachments=True,
        duplicate=False,
        failure=None,
        missing_body=False,
    ):
        self.state, self.after_state = state, after_state or state
        self.attachments, self.duplicate, self.failure, self.missing_body = (
            attachments,
            duplicate,
            failure,
            missing_body,
        )
        self.events, self.sessions = [], []
        self.files_markup, self.prepare_exception, self.download_html = FILES, False, False
        self.omit_callback_args = False
        self.config = PortalConfig()
        self.store = CookieSessionStore(tmp_path / "session.json")

    def login(self):
        session = Session(self, len(self.sessions))
        self.sessions.append(session)
        page = BeautifulSoup('<form id="menuForm" action="/uprx/list.xhtml"></form>', "lxml")
        return PortalAuthResult(session, response(""), page, True)


def reference():
    return parse_notices(BeautifulSoup(listing(), "lxml"))[0]["notice_ref"]


def test_read_detail_and_attachment_references_with_independent_verification(tmp_path):
    app = App(tmp_path)
    result = fetch_notice(PortalClient(app), reference())
    assert result.body == "One inline phrase\nSecond\nline"
    assert result.sender == "Synthetic office"
    assert result.attachments[0].name == "synthetic.pdf"
    assert result.attachments[0].download_supported
    assert result.read_state_unchanged
    assert app.events == ["list", "detail", "attachments", "list"]
    assert len(app.sessions) == 2
    assert all(session.closed for session in app.sessions)


@pytest.mark.parametrize("state,error", [("unread", ReadStateChangeRequired), ("unknown", ReadStateUnknown)])
@pytest.mark.parametrize("attachment_ref", [None, "b" * 64])
def test_unread_unknown_are_blocked_before_selection(tmp_path, state, error, attachment_ref):
    app = App(tmp_path, state=state)
    with pytest.raises(error):
        fetch_notice(PortalClient(app), reference(), attachment_ref=attachment_ref)
    assert app.events == ["list"]


def test_read_state_drift_withholds_result(tmp_path):
    app = App(tmp_path, after_state="unread")
    with pytest.raises(ReadStateVerificationFailed):
        fetch_notice(PortalClient(app), reference())


def test_missing_attachment_section_is_not_empty_success(tmp_path):
    app = App(tmp_path, attachments=False)
    result = fetch_notice(PortalClient(app), reference())
    assert result.attachments == []
    assert "attachments" not in app.events


def test_missing_body_is_failure_after_state_check(tmp_path):
    app = App(tmp_path, missing_body=True)
    with pytest.raises(StructureChanged):
        fetch_notice(PortalClient(app), reference())
    assert app.events[-1] == "list"


def test_network_failure_is_not_retried_and_still_checks_state(tmp_path):
    app = App(tmp_path, failure=requests.Timeout("private-sensitive-url"))
    with pytest.raises(requests.Timeout):
        fetch_notice(PortalClient(app), reference())
    assert app.events == ["list", "detail", "list"]


def test_invalid_reference_does_not_authenticate(tmp_path):
    app = App(tmp_path)
    with pytest.raises(ValueError):
        fetch_notice(PortalClient(app), "https://arbitrary.invalid/?secret=value")
    assert not app.events and not app.sessions


def test_not_found_and_duplicate_notice_never_select_detail(tmp_path):
    app = App(tmp_path)
    with pytest.raises(NoticeNotFound):
        fetch_notice(PortalClient(app), "0" * 64)
    app = App(tmp_path, duplicate=True)
    with pytest.raises(NoticeAmbiguous):
        fetch_notice(PortalClient(app), reference())
    assert app.events == ["list"]


def test_private_attachment_saved_only_after_state_verification(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    app = App(tmp_path)
    client = PortalClient(app)
    first = fetch_notice(client, reference())
    # The second operation has its own before/after views.
    result = fetch_notice(client, reference(), attachment_ref=first.attachments[0].attachment_ref)
    path = Path(result.file_path)
    assert path.read_bytes() == b"%PDF-synthetic-only"
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.parent.stat().st_mode & 0o777 == 0o700
    assert path.name == result.sha256 + ".pdf"
    assert "synthetic.pdf" not in path.name


def test_read_drift_never_writes_attachment(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    first = fetch_notice(PortalClient(App(tmp_path)), reference())
    app = App(tmp_path, after_state="unread")
    with pytest.raises(ReadStateVerificationFailed):
        fetch_notice(PortalClient(app), reference(), attachment_ref=first.attachments[0].attachment_ref)
    assert not (tmp_path / ".local/share/cit-campus-mcp/attachments").exists()


def test_unknown_client_handler_is_never_assumed_read():
    page = BeautifulSoup(listing(), "lxml")
    a = page.select_one("#keiji a")
    a["onclick"] += "unknownAction();"
    assert notice_read_state(a) == "unknown"


def test_preparation_exception_does_not_submit_or_write_download(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    first = fetch_notice(PortalClient(App(tmp_path)), reference())
    app = App(tmp_path)
    app.prepare_exception = True
    with pytest.raises(StructureChanged):
        fetch_notice(PortalClient(app), reference(), attachment_ref=first.attachments[0].attachment_ref)
    assert "prepare" in app.events and "download" not in app.events
    assert not (tmp_path / ".local/share/cit-campus-mcp/attachments").exists()


def test_unknown_download_callback_is_not_executed(tmp_path):
    app = App(tmp_path)
    app.files_markup = FILES.replace("exceptionFlg", "unrecognizedFlag")
    result = fetch_notice(PortalClient(app), reference())
    assert not result.attachments[0].download_supported
    assert "prepare" not in app.events and "download" not in app.events


def test_html_download_response_is_not_saved_as_file(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    first = fetch_notice(PortalClient(App(tmp_path)), reference())
    app = App(tmp_path)
    app.download_html = True
    with pytest.raises(StructureChanged):
        fetch_notice(PortalClient(app), reference(), attachment_ref=first.attachments[0].attachment_ref)
    assert not (tmp_path / ".local/share/cit-campus-mcp/attachments").exists()


def test_component_locator_disambiguates_identical_metadata():
    page = BeautifulSoup(listing(), "lxml")
    first = parse_notices(page)[0]
    a = page.select_one("#keiji a")
    a["id"] = SOURCE + "0"
    a["onclick"] = handler(a["id"])
    second = parse_notices(page)[0]
    assert first["title"] == second["title"] and first["notice_ref"] != second["notice_ref"]


def test_form_tokens_are_scoped_by_element_id():
    from cit_campus_mcp.portal.notices import _apply_updates, _form

    page = BeautifulSoup(
        """<form id="funcForm"><input type="hidden" id="funcForm:token" name="sharedName" value="main"></form>
    <form id="bsd001001:ch"><input type="hidden" id="bsd001001:token" name="sharedName" value="dialog"><button id="bsd001001:ch:button"></button></form>""",
        "lxml",
    )
    _apply_updates(
        page,
        response(
            partial(
                "funcForm:token", '<input type="hidden" id="funcForm:token" name="sharedName" value="updated-main">'
            )
        ),
    )
    _, data = _form(page, "bsd001001:ch:button", page.find("button"))
    assert data["sharedName"] == "dialog"


def test_cancelled_download_does_not_commit_local_file(tmp_path, monkeypatch):
    import cit_campus_mcp.portal.notices as notices

    class Cancelled(BaseException):
        pass

    checks = iter([None, Cancelled()])

    def check():
        value = next(checks)
        if value is not None:
            raise value

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(notices, "_check_cancelled", check)
    with pytest.raises(Cancelled):
        notices._store_attachment(b"synthetic", "application/pdf")
    assert not list((tmp_path / ".local/share/cit-campus-mcp/attachments").iterdir())


def test_normal_download_with_empty_callback_args(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    first = fetch_notice(PortalClient(App(tmp_path)), reference())
    app = App(tmp_path)
    app.omit_callback_args = True
    result = fetch_notice(PortalClient(app), reference(), attachment_ref=first.attachments[0].attachment_ref)
    assert Path(result.file_path).is_file()


def test_dialog_lifecycle_does_not_leave_a_stale_app_view(tmp_path):
    client = PortalClient(App(tmp_path))
    fetch_notice(client, reference())
    assert client.auth is None
    assert not client.cache
