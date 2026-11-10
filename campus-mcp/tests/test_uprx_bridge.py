from bs4 import BeautifulSoup

from cit_campus_mcp.webforms import find_auto_post_form, find_form_by_id


def _bridge_soup():
    return BeautifulSoup(
        """
        <html><body>
          <form id="infoForm" method="post" action="/uprx/up/pk/pky001/Pky00102.xhtml">
            <input type="hidden" name="infoForm" value="infoForm">
            <input type="hidden" name="javax.faces.ViewState" value="stateless">
          </form>
          <form id="errForm" method="post" action="/uprx/up/pk/pky001/Pky00102.xhtml">
            <input type="hidden" name="errForm" value="errForm">
            <input type="hidden" name="javax.faces.ViewState" value="stateless">
          </form>
          <form id="loginForm" method="post" action="/uprx/up/pk/pky001/Pky00102.xhtml">
            <input type="hidden" name="javax.faces.ViewState" value="stateless">
            <input type="hidden" name="loginForm" value="loginForm">
          </form>
        </body></html>
        """,
        "lxml",
    )


def test_uprx_bridge_selects_login_form_explicitly():
    soup = _bridge_soup()
    spec = find_form_by_id(
        soup,
        "https://portal.chibatech.ac.jp/uprx/up/pk/pky001/Pky00102.xhtml",
        "loginForm",
    )
    assert spec is not None
    assert spec.fields["loginForm"] == "loginForm"
    assert spec.fields["javax.faces.ViewState"] == "stateless"


def test_generic_auto_post_would_choose_wrong_form_on_bridge():
    # Regression documentation: the old generic detector sees infoForm first,
    # which is exactly why auth.py must special-case Pky00102 before it runs.
    soup = _bridge_soup()
    spec = find_auto_post_form(
        soup,
        "https://portal.chibatech.ac.jp/uprx/up/pk/pky001/Pky00102.xhtml",
    )
    assert spec is not None
    assert "infoForm" in spec.fields
