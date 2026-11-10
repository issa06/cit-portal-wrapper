from bs4 import BeautifulSoup

from cit_campus_mcp.webforms import (
    find_credential_form,
    find_otp_credentials,
    find_otp_form,
    find_sso_entry_url,
    select_otp_credential_id,
)


def test_portal_landing_prefers_shibboleth_sso_link():
    soup = BeautifulSoup(
        """
        <form id="loginForm">
          <a href="https://portal.chibatech.ac.jp/uprx/ShibbolethAuthServlet">
            在学生・教職員専用ログイン（統合認証）
          </a>
          <input name="loginForm:userId" type="text">
          <input name="loginForm:password" type="password">
        </form>
        """,
        "lxml",
    )
    assert find_sso_entry_url(soup, "https://portal.chibatech.ac.jp/") == (
        "https://portal.chibatech.ac.jp/uprx/ShibbolethAuthServlet"
    )


def test_keycloak_login_form_detection():
    soup = BeautifulSoup(
        """
        <form id="kc-form-login" action="https://sso.chibatech.ac.jp/realms/marine/login-actions/authenticate" method="post">
          <input id="username" name="username" type="text" autocomplete="username">
          <input id="password" name="password" type="password" autocomplete="current-password">
          <input type="hidden" name="credentialId" value="">
          <button name="login" id="kc-login" type="submit">Sign In</button>
        </form>
        """,
        "lxml",
    )
    form = find_credential_form(soup, "https://sso.chibatech.ac.jp/start")
    assert form is not None
    assert form.user_field == "username"
    assert form.password_field == "password"
    assert form.submit_fields == ("login",)


def test_keycloak_otp_selects_python_credential():
    soup = BeautifulSoup(
        """
        <form id="kc-otp-login-form" action="https://sso.chibatech.ac.jp/realms/marine/login-actions/authenticate" method="post">
          <input id="selectedCredentialId" type="hidden" name="selectedCredentialId" value="apple-id">
          <div id="kc-otp-credential-0" onclick="toggleOTP(0, 'apple-id')">
            <span class="pf-v5-c-tile__title">Apple</span>
          </div>
          <div id="kc-otp-credential-1" onclick="toggleOTP(1, 'python-id')">
            <span class="pf-v5-c-tile__title">Python</span>
          </div>
          <input id="otp" name="otp" type="text" autocomplete="one-time-code">
          <button name="login" type="submit">Sign In</button>
        </form>
        """,
        "lxml",
    )
    form = find_otp_form(soup, "https://sso.chibatech.ac.jp/start")
    assert form is not None
    assert form.otp_field == "otp"
    assert form.fields["selectedCredentialId"] == "apple-id"
    credentials = find_otp_credentials(soup)
    assert [(c.label, c.credential_id) for c in credentials] == [
        ("Apple", "apple-id"),
        ("Python", "python-id"),
    ]
    assert select_otp_credential_id(soup, "Python") == "python-id"


def test_keycloak_login_form_exposes_remember_me_field_name():
    soup = BeautifulSoup(
        """
        <form id="kc-form-login" action="https://sso.chibatech.ac.jp/realms/marine/login-actions/authenticate" method="post">
          <input id="username" name="username" type="text">
          <input id="password" name="password" type="password">
          <input id="rememberMe" name="rememberMe" type="checkbox">
          <button name="login" type="submit">Sign In</button>
        </form>
        """,
        "lxml",
    )
    form = find_credential_form(soup, "https://sso.chibatech.ac.jp/start")
    assert form is not None
    assert "rememberMe" in form.field_names
    # Unchecked checkboxes must not be submitted unless auth explicitly enables it.
    assert "rememberMe" not in form.fields
