from bs4 import BeautifulSoup

from cit_campus_mcp.totp import generate_totp
from cit_campus_mcp.webforms import find_credential_form, find_otp_form


def test_detect_credential_form():
    soup = BeautifulSoup(
        """
        <form action="/login" method="post">
          <input type="hidden" name="csrf" value="abc">
          <input type="text" name="username">
          <input type="password" name="password">
          <button type="submit" name="login">Login</button>
        </form>
        """,
        "lxml",
    )
    form = find_credential_form(soup, "https://sso.example.edu/start")
    assert form is not None
    assert form.user_field == "username"
    assert form.password_field == "password"
    assert form.fields["csrf"] == "abc"


def test_detect_otp_form():
    soup = BeautifulSoup(
        """
        <form action="/mfa" method="post">
          <input type="hidden" name="RelayState" value="xyz">
          <label>認証コード <input type="text" name="otpCode"></label>
          <button type="submit">Verify</button>
        </form>
        """,
        "lxml",
    )
    form = find_otp_form(soup, "https://sso.example.edu/mfa")
    assert form is not None
    assert form.otp_field == "otpCode"


def test_totp_rfc6238_sha1_vector():
    secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
    assert generate_totp(secret, timestamp=59, digits=8, interval=30, algorithm="SHA1") == "94287082"
    assert generate_totp(secret, timestamp=1111111109, digits=8, interval=30, algorithm="SHA1") == "07081804"
