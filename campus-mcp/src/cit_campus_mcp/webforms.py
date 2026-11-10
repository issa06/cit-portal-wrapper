from __future__ import annotations

import re
import warnings
from dataclasses import dataclass
from typing import Iterable
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup, Tag, XMLParsedAsHTMLWarning

from .errors import AuthenticationError, ServiceUnavailable, SessionExpired, StructureChanged

USER_HINTS = ("user", "username", "userid", "login", "account", "email", "mail", "id")
PASSWORD_HINTS = ("pass", "password", "passwd", "pwd")
OTP_HINTS = ("otp", "totp", "mfa", "2fa", "code", "token", "verify", "verification", "authcode")


@dataclass(frozen=True)
class FormSpec:
    action: str
    method: str
    fields: dict[str, str]
    user_field: str | None = None
    password_field: str | None = None
    otp_field: str | None = None
    submit_fields: tuple[str, ...] = ()
    field_names: tuple[str, ...] = ()


@dataclass(frozen=True)
class OtpCredential:
    label: str
    credential_id: str


def soup_from_response(response: requests.Response) -> BeautifulSoup:
    # CIT UPRX serves XHTML-looking markup as HTML on some endpoints. BeautifulSoup's
    # lxml HTML parser handles both the UPRX pages and Keycloak pages consistently;
    # suppress only the advisory warning caused by the XHTML namespace.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", XMLParsedAsHTMLWarning)
        return BeautifulSoup(response.content, "lxml")


def portal_page(response: requests.Response) -> BeautifulSoup:
    """Decode both ordinary HTML and JSF partial-response CDATA, without executing JS."""
    response.raise_for_status()
    soup = soup_from_response(response)
    if soup.find("partial-response"):
        xml = BeautifulSoup(response.content, "xml")
        if xml.find("redirect"):
            raise SessionExpired("Portal requested a new navigation session.")
        if xml.find("error"):
            raise ServiceUnavailable("Portal returned a JSF error.")
        updates = xml.find_all("update")
        if not updates:
            raise StructureChanged("JSF response contains no updates.")
        markup = "".join(str(u.string or "") for u in updates if not str(u.get("id", "")).endswith("ViewState"))
        soup = BeautifulSoup(markup, "lxml")
        state = next((u.string for u in updates if str(u.get("id", "")).endswith("ViewState")), None)
        if state:
            for tag in soup.select('input[name="javax.faces.ViewState"]'):
                tag["value"] = str(state)
    if find_credential_form(soup, response.url) or find_otp_form(soup, response.url):
        raise SessionExpired("Portal session expired.")
    return soup


def _name(input_tag: Tag) -> str | None:
    name = input_tag.get("name")
    return str(name) if name else None


def _input_candidates(form: Tag) -> list[Tag]:
    return [tag for tag in form.find_all(["input", "textarea", "select"]) if isinstance(tag, Tag)]


def _field_blob(tag: Tag) -> str:
    parts = [
        str(tag.get("name") or ""),
        str(tag.get("id") or ""),
        str(tag.get("placeholder") or ""),
        str(tag.get("autocomplete") or ""),
        str(tag.get("aria-label") or ""),
    ]
    return " ".join(parts).lower()


def _first_by_type(form: Tag, types: Iterable[str]) -> str | None:
    wanted = {t.lower() for t in types}
    for tag in form.find_all("input"):
        if str(tag.get("type") or "text").lower() in wanted and _name(tag):
            return _name(tag)
    return None


def _first_by_hint(form: Tag, hints: Iterable[str], excluded_types: set[str] | None = None) -> str | None:
    excluded = excluded_types or set()
    for tag in _input_candidates(form):
        if str(tag.get("type") or "text").lower() in excluded:
            continue
        blob = _field_blob(tag)
        if any(h in blob for h in hints) and _name(tag):
            return _name(tag)
    return None


def _default_fields(form: Tag) -> dict[str, str]:
    fields: dict[str, str] = {}
    for tag in form.find_all(["input", "textarea", "select"]):
        name = _name(tag)
        if not name:
            continue
        tag_name = tag.name.lower()
        input_type = str(tag.get("type") or "text").lower()
        if input_type in {"file", "reset", "button", "submit"}:
            continue
        if input_type in {"checkbox", "radio"} and not tag.has_attr("checked"):
            continue
        if tag_name == "select":
            selected = tag.find("option", selected=True) or tag.find("option")
            fields[name] = str(selected.get("value") or "") if selected else ""
        elif tag_name == "textarea":
            fields[name] = tag.get_text()
        else:
            fields[name] = str(tag.get("value") or "")
    return fields


def inspect_form(form: Tag, base_url: str) -> FormSpec:
    action = urljoin(base_url, str(form.get("action") or base_url))
    method = str(form.get("method") or "post").lower()
    fields = _default_fields(form)

    password = _first_by_type(form, ["password"]) or _first_by_hint(form, PASSWORD_HINTS)
    user = _first_by_hint(form, USER_HINTS, {"hidden", "password", "submit", "button"})
    if not user:
        user = _first_by_type(form, ["text", "email"])

    otp = _first_by_hint(form, OTP_HINTS, {"hidden", "password", "submit", "button"})
    if not otp and not password:
        visible_text = [
            _name(tag)
            for tag in form.find_all("input")
            if str(tag.get("type") or "text").lower() in {"text", "tel", "number"} and _name(tag)
        ]
        if len(visible_text) == 1:
            form_text = form.get_text(" ", strip=True).lower()
            if any(word in form_text for word in ("otp", "認証コード", "確認コード", "ワンタイム", "verification")):
                otp = visible_text[0]

    submit_fields: list[str] = []
    for tag in form.find_all(["input", "button"]):
        input_type = str(tag.get("type") or "").lower()
        if input_type == "submit" and _name(tag):
            submit_fields.append(_name(tag) or "")

    field_names = tuple(name for tag in _input_candidates(form) if (name := _name(tag)))

    return FormSpec(
        action=action,
        method=method,
        fields=fields,
        user_field=user,
        password_field=password,
        otp_field=otp,
        submit_fields=tuple(submit_fields),
        field_names=field_names,
    )


def find_sso_entry_url(soup: BeautifulSoup, base_url: str) -> str | None:
    """Find the student/staff Shibboleth SSO entry link on the UPRX landing page."""
    candidates: list[tuple[int, str]] = []
    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href") or "")
        text = anchor.get_text(" ", strip=True).lower()
        blob = f"{href} {text}".lower()
        score = 0
        if "shibbolethauthservlet" in blob:
            score += 100
        if "統合認証" in blob:
            score += 50
        if "shibboleth" in blob:
            score += 25
        if "sso" in blob:
            score += 10
        if score:
            candidates.append((score, urljoin(base_url, href)))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def find_credential_form(soup: BeautifulSoup, base_url: str) -> FormSpec | None:
    specs = [inspect_form(form, base_url) for form in soup.find_all("form")]
    for spec in specs:
        if spec.password_field:
            return spec
    return None


def find_otp_form(soup: BeautifulSoup, base_url: str) -> FormSpec | None:
    specs = [inspect_form(form, base_url) for form in soup.find_all("form")]
    for spec in specs:
        if spec.otp_field and not spec.password_field:
            return spec
    return None


def find_otp_credentials(soup: BeautifulSoup) -> list[OtpCredential]:
    """Return Keycloak OTP credential tiles (for example Apple/Python)."""
    found: list[OtpCredential] = []
    seen: set[str] = set()
    for tile in soup.select('[id^="kc-otp-credential-"]'):
        onclick = str(tile.get("onclick") or "")
        match = re.search(r"toggleOTP\(\s*\d+\s*,\s*['\"]([^'\"]+)['\"]\s*\)", onclick)
        if not match:
            continue
        credential_id = match.group(1)
        label_tag = tile.select_one(".pf-v5-c-tile__title")
        label = label_tag.get_text(" ", strip=True) if label_tag else tile.get_text(" ", strip=True)
        if credential_id not in seen:
            found.append(OtpCredential(label=label, credential_id=credential_id))
            seen.add(credential_id)
    return found


def select_otp_credential_id(soup: BeautifulSoup, label: str) -> str | None:
    credentials = find_otp_credentials(soup)
    if not credentials:
        return None
    wanted = label.strip().casefold()
    if wanted:
        for credential in credentials:
            if credential.label.strip().casefold() == wanted:
                return credential.credential_id
        for credential in credentials:
            if wanted in credential.label.strip().casefold():
                return credential.credential_id
        return None
    if len(credentials) == 1:
        return credentials[0].credential_id
    return None


def find_form_by_id(soup: BeautifulSoup, base_url: str, form_id: str) -> FormSpec | None:
    """Return a specific form by HTML id/name.

    This is used for UPRX post-SSO bridge pages where multiple hidden-only
    JSF forms coexist and only the dedicated loginForm is part of the
    authentication handshake.
    """
    form = soup.find("form", id=form_id) or soup.find("form", attrs={"name": form_id})
    if not isinstance(form, Tag):
        return None
    return inspect_form(form, base_url)


def find_auto_post_form(soup: BeautifulSoup, base_url: str) -> FormSpec | None:
    for form in soup.find_all("form"):
        spec = inspect_form(form, base_url)
        inputs = form.find_all("input")
        if inputs and all(str(tag.get("type") or "hidden").lower() in {"hidden", "submit"} for tag in inputs):
            hidden_count = sum(str(tag.get("type") or "hidden").lower() == "hidden" for tag in inputs)
            if hidden_count >= 2:
                return spec
    return None


def submit_form(
    session: requests.Session,
    spec: FormSpec,
    values: dict[str, str],
    timeout: int,
    submit_override: str = "",
) -> requests.Response:
    data = dict(spec.fields)
    data.update(values)
    submit_name = submit_override or (spec.submit_fields[0] if spec.submit_fields else "")
    if submit_name and submit_name not in data:
        data[submit_name] = ""
    parsed = urlparse(spec.action)
    if parsed.scheme and parsed.scheme != "https":
        raise AuthenticationError("Refusing to submit credentials to a non-HTTPS URL.")
    if spec.method == "get":
        if spec.password_field or spec.otp_field:
            raise AuthenticationError("Refusing to submit credentials in URL parameters.")
        return session.get(spec.action, params=data, timeout=timeout, allow_redirects=True)
    return session.post(spec.action, data=data, timeout=timeout, allow_redirects=True)


def find_client_redirect(soup: BeautifulSoup, base_url: str) -> str | None:
    meta = soup.find("meta", attrs={"http-equiv": re.compile("refresh", re.I)})
    if meta and meta.get("content"):
        content = str(meta.get("content"))
        match = re.search(r"url\s*=\s*['\"]?([^'\";]+)", content, re.I)
        if match:
            return urljoin(base_url, match.group(1).strip())

    scripts = "\n".join(script.get_text(" ", strip=True) for script in soup.find_all("script"))
    match = re.search(r"(?:window\.)?location(?:\.href)?\s*=\s*['\"]([^'\"]+)['\"]", scripts, re.I)
    if match:
        return urljoin(base_url, match.group(1))
    return None


def auth_error_text(soup: BeautifulSoup) -> str | None:
    """Extract only short, visible authentication error text from common Keycloak containers."""
    selectors = (
        ".pf-v5-c-alert__title",
        ".kc-feedback-text",
        "#input-error",
        "[id^='input-error-container-'] .pf-v5-c-helper-text__item-text",
        "[role='alert']",
    )
    for selector in selectors:
        tag = soup.select_one(selector)
        if tag:
            text = tag.get_text(" ", strip=True)
            if text:
                return text[:300]
    return None


def sanitized_form_summary(soup: BeautifulSoup, base_url: str) -> list[dict[str, object]]:
    summary: list[dict[str, object]] = []
    for form in soup.find_all("form"):
        spec = inspect_form(form, base_url)
        summary.append(
            {
                "action_host": urlparse(spec.action).netloc,
                "action_path": urlparse(spec.action).path,
                "method": spec.method,
                "field_names": sorted(spec.fields),
                "user_field": spec.user_field,
                "password_field": spec.password_field,
                "otp_field": spec.otp_field,
            }
        )
    return summary
