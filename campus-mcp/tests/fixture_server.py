"""Synthetic stdio server fixture. Never used by production entry points."""

import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import requests

from cit_campus_mcp import server
from cit_campus_mcp.errors import AuthenticationError


def dataset(*args, **kwargs):
    if os.environ.get("CIT_TEST_MODE") == "slow":
        time.sleep(0.8)
    if os.environ.get("CIT_TEST_MODE") == "errors":
        raise requests.Timeout("synthetic-private-url?token=synthetic-secret")
    return {
        "items": [{"title": "Synthetic", "date": "2026-11-01", "category": "Test"}],
        "fetched_at": "2026-11-10T00:00:00+00:00",
        "source": "https://portal.chibatech.ac.jp/",
    }


def status():
    if os.environ.get("CIT_TEST_MODE") == "errors":
        raise AuthenticationError("synthetic-password")
    return {"authenticated": True, "restored_session": True, "menu_form": True}


server._dataset = dataset
server._portal = lambda: SimpleNamespace(status=status, run=lambda *args, **kwargs: {"Synthetic": "Only"})
server._manaba = lambda: SimpleNamespace(
    list_courses=lambda: [{"course_id": "1", "name": "Test", "url": "https://cit.manaba.jp/ct/course_1"}],
    list_action_items=lambda: [],
    get_page_text=lambda _: {"title": "Test", "text": "Synthetic"},
)
server._documents = lambda: SimpleNamespace(
    list_links=lambda: [],
    search=lambda *args: [],
    get_text=lambda *args: {
        "title": "Test",
        "url": "https://kmsk.is.it-chiba.ac.jp/portal/test",
        "kind": "html",
        "text": "Synthetic",
    },
)
server.main()
