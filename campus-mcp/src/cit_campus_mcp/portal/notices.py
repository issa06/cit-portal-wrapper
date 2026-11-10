"""Notice details: do not select unread/unknown records or execute response JavaScript.

The observed UPRX renderer uses fontBold for unread command links. Only its exact
known normal-link shape is accepted as already read. No claim is made that the
server's detail action is read-only for unread notices.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from ..errors import (
    NoticeAmbiguous,
    NoticeNotFound,
    ReadStateChangeRequired,
    ReadStateUnknown,
    ReadStateVerificationFailed,
    ResponseTooLarge,
    StructureChanged,
)
from ..models import NoticeAttachment, NoticeDetail, NoticeDownload
from ..session_store import session_lock
from ..webforms import portal_page

_LINK_ID = re.compile(r"funcForm:tabArea:\d+:(?:j_idt\d+:\d+:)+j_idt\d+\Z")
_DETAIL_PANEL = re.compile(r"bsd\d+:dialogPanel\Z")
_FILE_PANEL = re.compile(r"pkx\d+:dialogPanel\Z")
_FILE_BUTTON = re.compile(r"(?P<row>pkx\d+:ch:appendList:\d+):j_idt\d+\Z")


def notice_reference(record: dict, component_id: str | None = None) -> str:
    # Bind selection to both metadata and its current view locator. Credentials,
    # URL queries and ViewState never enter a reference. Stale locators fail closed.
    metadata = [record.get(k) for k in ("date", "category", "title")]
    if component_id is not None:
        metadata.append(component_id)
    return hashlib.sha256(json.dumps(metadata, ensure_ascii=False).encode()).hexdigest()


def _ajax_fields(node: Tag) -> tuple[str, str]:
    source = str(node.get("id", ""))
    code = str(node.get("onclick", ""))
    match = re.search(r"\bs\s*:\s*(['\"])([^'\"]+)\1", code)
    process = re.search(r"\bp\s*:\s*(['\"])([^'\"]+)\1", code)
    if not source or not match or match[2] != source:
        raise StructureChanged("The advertised notice action is unsupported.")
    return source, process[2] if process else source


def notice_read_state(anchor: Tag) -> str:
    container = anchor.parent
    if (
        not isinstance(container, Tag)
        or container.name != "dl"
        or container.get("id") != "keiji"
        or "keiji" not in container.get("class", [])
        or len(container.find_all("a")) != 1
        or not _LINK_ID.fullmatch(str(anchor.get("id", "")))
    ):
        return "unknown"
    classes = set(anchor.get("class", []))
    if classes not in ({"ui-commandlink", "ui-widget"}, {"ui-commandlink", "ui-widget", "fontBold"}):
        return "unknown"
    try:
        source, process = _ajax_fields(anchor)
    except StructureChanged:
        return "unknown"
    # Unknown extra client behavior or styling is never interpreted as "already read".
    code = str(anchor.get("onclick", ""))
    simple = re.fullmatch(
        rf"\s*PrimeFaces\.ab\(\{{s:([\"']){re.escape(source)}\1,p:([\"']){re.escape(source)}\2\}}\);return false;?\s*",
        code,
    )
    if process != source or not simple or anchor.has_attr("style"):
        return "unknown"
    return "unread" if "fontBold" in classes else "read"


def _snapshot(page: BeautifulSoup) -> Counter:
    from .parsers import parse_notices

    # Locators can move when the view reloads; preserve duplicate multiplicity and
    # compare the displayed metadata/read state, independently of component IDs.
    return Counter((notice_reference(r), r["read_state"]) for r in parse_notices(page))


def _fresh_top(client):
    # Repeating the current menu in UPRX can be a no-op partial response, not a
    # newly read list. Independent app views are essential to the state check.
    previous = client.auth
    client.auth = client.authenticator.login()
    if previous is not None and previous.session is not client.auth.session:
        previous.session.close()
    return client.connect()


def _listing(client, full: bool, wanted: str | None = None):
    from .parsers import iter_notice_pages, parse_notices

    top = _fresh_top(client)
    snapshot, matches, last_page, selected_page = Counter(), [], None, None
    for page in iter_notice_pages(top, full):
        snapshot.update(_snapshot(page))
        last_page = page
        if wanted:
            for record, anchor in zip(parse_notices(page), [n.select_one("a") for n in page.select("#keiji")]):
                if record["notice_ref"] == wanted:
                    matches.append((record, anchor))
                    selected_page = page
    client.auth.soup = top.soup
    return top, snapshot, matches, selected_page, last_page


def _select_page(client, full: bool, wanted: str):
    from .parsers import iter_notice_pages, parse_notices

    top = _fresh_top(client)
    for page in iter_notice_pages(top, full):
        for record, anchor in zip(parse_notices(page), [n.select_one("a") for n in page.select("#keiji")]):
            if record["notice_ref"] == wanted:
                return top, page, record, anchor
    raise NoticeNotFound("The notice is no longer in the requested list.")


def _response_state(page: BeautifulSoup) -> dict:
    # Keep private form values in Python memory, outside serialized HTML/output.
    return page.__dict__.setdefault("_notice_response_state", {"view_state": None, "inputs": {}, "panels": {}})


def _apply_updates(page: BeautifulSoup, response):
    portal_page(response)
    xml = BeautifulSoup(response.content, "xml")
    if not xml.find("partial-response"):
        raise StructureChanged("Expected a JSF partial response.")
    state, panels = _response_state(page), []
    for update in xml.find_all("update"):
        identity = str(update.get("id", ""))
        markup = update.get_text()
        if re.search(r"(?:^|:)javax\.faces\.ViewState(?::\d+)?$", identity):
            state["view_state"] = markup
            continue
        fragment = BeautifulSoup(markup, "lxml")
        for field in fragment.select('input[type="hidden"][name]'):
            if field.get("id"):
                state["inputs"][field["id"]] = field.get("value", "")
        if _DETAIL_PANEL.fullmatch(identity) or _FILE_PANEL.fullmatch(identity):
            panel = fragment.find(id=identity)
            if panel is None:
                panel = fragment.new_tag("div", id=identity)
                for child in list((fragment.body or fragment).contents):
                    panel.append(child.extract())
            # Preserve each dialog's advertised forms in its standalone fragment.
            # Reparenting nested forms into a stale page can change form ownership.
            state["panels"][identity] = panel
            panels.append(panel)
    # eval/onShow/onClose/read/receipt/flag/print callbacks are never executed.
    return panels, xml


def _form(page: BeautifulSoup, source: str, control: Tag | None = None):
    form = control.find_parent("form") if control is not None else None
    if form is None:
        node = page.find(id=source)
        form = node.find_parent("form") if node is not None else None
    if form is None:
        form = page.find("form", id=source.split(":", 1)[0])
    if form is None:
        raise StructureChanged("The notice form is missing.")
    state = _response_state(page)
    data = {
        n["name"]: state["inputs"].get(n.get("id"), n.get("value", ""))
        for n in form.select('input[type="hidden"][name]')
    }
    if state["view_state"] is not None:
        data["javax.faces.ViewState"] = state["view_state"]
    return form, data


def _ajax(top, page: BeautifulSoup, control: Tag):
    source, process = _ajax_fields(control)
    form, data = _form(page, source, control)
    data.update(
        {
            "javax.faces.partial.ajax": "true",
            "javax.faces.source": source,
            "javax.faces.partial.execute": process,
            source: source,
        }
    )
    response = top.session.post(
        urljoin(top.config.home_url, str(form.get("action", ""))), data=data, timeout=top.config.timeout
    )
    return _apply_updates(page, response)


def _label_values(panel: Tag) -> dict[str, Tag]:
    values = {}
    # Read only direct header/data pairs, never labels injected inside the rich body.
    for row in panel.select("table.ui-panelgrid > tbody > tr"):
        cells = row.find_all(["th", "td"], recursive=False)
        for index, cell in enumerate(cells[:-1]):
            if "ui-widget-header" in cell.get("class", []):
                label = cell.get_text(" ", strip=True).rstrip("：:")
                if label in {"差出人", "本文", "件名", "カテゴリ", "掲示期間"}:
                    if label in values:
                        raise StructureChanged("Duplicate notice detail fields.")
                    values[label] = cells[index + 1]
    return values


def _plain_text(node: Tag) -> str:
    clean = BeautifulSoup(str(node), "lxml")
    for tag in clean.select("script, style, iframe, object, input, button"):
        tag.decompose()
    for tag in clean.find_all("br"):
        tag.replace_with("\n")
    for tag in clean.find_all(["p", "div", "li", "tr"]):
        tag.append("\n")
    # Preserve inline spans and intentional line breaks, without returning executable HTML.
    text = clean.get_text()
    return "\n".join(line.rstrip() for line in text.splitlines()).strip()


def _attachment_controls(panel: Tag, notice_ref: str):
    result = []
    for button in panel.find_all("button"):
        match = _FILE_BUTTON.fullmatch(str(button.get("id", "")))
        if not match or "PrimeFaces.ab" not in str(button.get("onclick", "")):
            continue
        source, _ = _ajax_fields(button)
        name_tag = button.select_one(".ui-button-text") or button
        name = name_tag.get_text(" ", strip=True)
        if not name or len(name) > 512:
            raise StructureChanged("Attachment name is missing or unsupported.")
        row = match["row"]
        hidden = _download_control(panel, button, row)
        reference = hashlib.sha256(
            json.dumps([notice_ref, name, row.rsplit(":", 1)[1]], ensure_ascii=False).encode()
        ).hexdigest()
        result.append(
            (
                NoticeAttachment(attachment_ref=reference, name=name, download_supported=hidden is not None),
                button,
                hidden,
            )
        )
    if not result:
        raise StructureChanged("Attachment list controls were not found.")
    return result


def _download_control(panel: Tag, prepare: Tag, row: str) -> Tag | None:
    # The observed UI checks exceptionFlg, then clicks an advertised PF widget.
    # Recognize that flow without evaluating any callback or guessing a sibling.
    callback = re.search(
        r"if\s*\(\s*!\s*args\.exceptionFlg\s*\)\s*\{\s*PF\(\s*(['\"])([A-Za-z_][A-Za-z0-9_]*)\1\s*\)\.getJQ\(\)\.click\(\);?\s*\}",
        str(prepare.get("onclick", "")),
    )
    if callback is None:
        return None
    for script in panel.find_all("script"):
        match = re.search(
            r"PrimeFaces\.cw\(\s*(['\"])CommandButton\1\s*,\s*(['\"])"
            + re.escape(callback[2])
            + r"\2\s*,\s*\{\s*id:\s*(['\"])([^'\"]+)\3",
            script.get_text(),
        )
        if match is None:
            continue
        button = panel.find("button", id=match[4])
        if (
            button is None
            or not str(button.get("id", "")).startswith(row + ":")
            or button.get("id") == prepare.get("id")
            or button.get("type") != "submit"
            or button.get("name") != button.get("id")
        ):
            return None
        assignment = str(button.get("onclick", ""))
        if not re.fullmatch(
            r"\s*(?:this\.form\.target\s*=\s*(['\"])(?:[A-Za-z_][A-Za-z0-9_.:-]{0,127})?\1;?\s*)?(?:return true;?\s*)?",
            assignment,
        ):
            return None
        return button
    return None


def _open(top, page, anchor, record):
    panels, _ = _ajax(top, page, anchor)
    details = [p for p in panels if _DETAIL_PANEL.fullmatch(str(p.get("id", "")))]
    if len(details) != 1:
        raise StructureChanged("Notice detail panel was not found.")
    panel = details[0]
    values = _label_values(panel)
    if "本文" not in values:
        raise StructureChanged("Notice body field was not found.")
    body = _plain_text(values["本文"])
    sender = _plain_text(values["差出人"]) if "差出人" in values else None
    attachment_buttons = [
        b
        for b in panel.find_all("button")
        if re.fullmatch(r"bsd\d+:ch:j_idt\d+", str(b.get("id", "")))
        and "添付" in (b.get_text(" ", strip=True) + str(b.get("title", "")))
        and b.find_parent(class_="fr-view") is None
    ]
    if len(attachment_buttons) != 1:
        raise StructureChanged("Attachment availability control was not found.")
    button = attachment_buttons[0]
    disabled = (
        button.has_attr("disabled")
        or button.get("aria-disabled") == "true"
        or "ui-state-disabled" in button.get("class", [])
    )
    attachments = []
    if not disabled:
        panels, _ = _ajax(top, page, button)
        files = [p for p in panels if _FILE_PANEL.fullmatch(str(p.get("id", "")))]
        if len(files) != 1:
            raise StructureChanged("Attachment panel was not found.")
        attachments = _attachment_controls(files[0], record["notice_ref"])
    return body, sender, attachments


def _download(top, page, attachment):
    metadata, prepare, hidden = attachment
    if hidden is None:
        raise StructureChanged("Attachment download action is unsupported.")
    _, prepared = _ajax(top, page, prepare)
    arguments = {}
    for extension in prepared.find_all("extension", attrs={"type": "args"}):
        try:
            values = json.loads(extension.get_text())
        except (TypeError, ValueError):
            raise StructureChanged("Attachment preparation was not confirmed.") from None
        if not isinstance(values, dict):
            raise StructureChanged("Attachment preparation was not confirmed.")
        arguments.update(values)
    # Match the advertised !args.exceptionFlg condition: PF supplies an empty
    # args object when no callback arguments were emitted. Do not invent a
    # mandatory flag that the actual normal download flow does not provide.
    if arguments.get("exceptionFlg") not in (None, False) or arguments.get("validationFailed") is True:
        raise StructureChanged("Attachment preparation was not confirmed.")
    # Follow only the observed normal form submit, not arbitrary callback code/URLs.
    for panel in _response_state(page)["panels"].values():
        hidden = panel.find(id=hidden["id"]) or hidden
    source = str(hidden["name"])
    form, data = _form(page, source, hidden)
    data[source] = source
    response = top.session.post(
        urljoin(top.config.home_url, str(form.get("action", ""))), data=data, timeout=top.config.timeout
    )
    response.raise_for_status()
    mime = response.headers.get("Content-Type", "application/octet-stream").split(";", 1)[0].lower()
    if not response.content or mime in {"text/html", "text/xml", "application/xml", "application/xhtml+xml"}:
        raise StructureChanged("The attachment request did not return a file.")
    if mime not in {
        "application/pdf",
        "application/octet-stream",
        "application/zip",
        "image/png",
        "image/jpeg",
        "image/gif",
        "text/plain",
        "text/csv",
        "application/msword",
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }:
        mime = "application/octet-stream"
    if len(response.content) > 8 * 1024 * 1024:
        raise ResponseTooLarge("Attachment download limit reached.")
    return metadata, response.content, mime


def _store_attachment(content: bytes, mime: str) -> tuple[str, str]:
    _check_cancelled()
    directory = Path.home() / ".local/share/cit-campus-mcp/attachments"
    if directory.is_symlink():
        raise StructureChanged("Attachment storage must be a private directory.")
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory.chmod(0o700)
    digest = hashlib.sha256(content).hexdigest()
    suffix = {
        "application/pdf": ".pdf",
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "application/zip": ".zip",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    }.get(mime, ".bin")
    target = directory / (digest + suffix)
    if target.is_symlink():
        raise StructureChanged("Attachment storage path is unsafe.")
    if (
        sum(p.stat().st_size for p in directory.iterdir() if p.is_file() and p != target) + len(content)
        > 200 * 1024 * 1024
    ):
        raise ResponseTooLarge("Local attachment storage limit reached.")
    fd, name = tempfile.mkstemp(prefix=".download-", dir=directory)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        _check_cancelled()
        os.replace(name, target)
    finally:
        Path(name).unlink(missing_ok=True)
    return str(target), digest


def _check_cancelled() -> None:
    import anyio

    try:
        anyio.from_thread.check_cancelled()
    except RuntimeError:
        pass  # Direct synchronous API use has no AnyIO worker context.


def fetch_notice(client, notice_ref: str, *, full: bool = False, attachment_ref: str | None = None):
    """Fetch already-read details/files; withhold output if state verification fails."""
    if not re.fullmatch(r"[0-9a-f]{64}", notice_ref) or (
        attachment_ref is not None and not re.fullmatch(r"[0-9a-f]{64}", attachment_ref)
    ):
        raise ValueError("Use a reference returned by the notice tools.")
    with client.lock, session_lock(client.authenticator.store.path.with_name("portal-operation.lock")):
        try:
            return _fetch_locked(client, notice_ref, full=full, attachment_ref=attachment_ref)
        finally:
            if client.auth is not None:
                client.auth.session.close()
                client.auth = None


def _fetch_locked(client, notice_ref: str, *, full: bool, attachment_ref: str | None):
    client.cache.clear()
    top, before, matches, page, last_page = _listing(client, full, notice_ref)
    if not matches:
        raise NoticeNotFound("The notice was not found in the requested list.")
    if len(matches) != 1:
        raise NoticeAmbiguous("The notice metadata is not unique.")
    record, anchor = matches[0]
    if record["read_state"] == "unread":
        raise ReadStateChangeRequired("Unread notice selection may change its read state; request blocked.")
    if record["read_state"] != "read" or any(state == "unknown" for _, state in before):
        raise ReadStateUnknown("Notice read state cannot be verified; request blocked.")
    if any(state != "read" for metadata, state in before if metadata == notice_reference(record)):
        raise ReadStateUnknown("Conflicting read-state displays; request blocked.")
    if page is not last_page:
        top, page, record, anchor = _select_page(client, full, notice_ref)
        if record["read_state"] != "read":
            raise ReadStateUnknown("Notice read state changed before selection; request blocked.")
    pending_error, downloaded = None, None
    try:
        body, sender, attachments = _open(top, page, anchor, record)
        if attachment_ref is not None:
            selected = [a for a in attachments if a[0].attachment_ref == attachment_ref]
            if len(selected) != 1:
                raise NoticeNotFound("The attachment was not found.")
            downloaded = _download(top, page, selected[0])
        fetched_at = datetime.now(timezone.utc).isoformat()
    except Exception as exc:
        pending_error = exc
    except BaseException:
        client.auth.session.close()
        client.auth = None
        raise
    try:
        _, after, _, _, _ = _listing(client, full)
    except Exception:
        if client.auth is not None:
            client.auth.session.close()
            client.auth = None
        raise ReadStateVerificationFailed("Unable to verify notice read state after retrieval.") from None
    except BaseException:
        if client.auth is not None:
            client.auth.session.close()
            client.auth = None
        raise
    if not before or before != after:
        raise ReadStateVerificationFailed("Notice list/read state changed; result withheld.")
    if pending_error is not None:
        raise pending_error
    if downloaded is not None:
        metadata, content, mime = downloaded
        path, digest = _store_attachment(content, mime)
        return NoticeDownload(
            notice_ref=notice_ref,
            attachment_ref=attachment_ref,
            name=metadata.name,
            file_path=path,
            content_type=mime,
            size_bytes=len(content),
            sha256=digest,
            fetched_at=fetched_at,
        )
    return NoticeDetail(
        notice_ref=notice_ref,
        title=record["title"],
        date=record["date"],
        category=record["category"],
        sender=sender,
        body=body,
        attachments=[a[0] for a in attachments],
        fetched_at=fetched_at,
        source=top.config.app_base.rstrip("/") + "/uprx/up/bs/bsd007/Bsd00701.xhtml",
    )
