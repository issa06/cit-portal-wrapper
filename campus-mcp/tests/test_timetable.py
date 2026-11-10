import anyio
import pytest
from bs4 import BeautifulSoup

from cit_campus_mcp import server
from cit_campus_mcp.errors import StructureChanged
from cit_campus_mcp.portal.parsers import parse_timetable

BLOCK = """<div><div class="fontB">Synthetic course</div><div>Synthetic teacher</div>
<div><span>Campus</span><span>Room</span></div><div class="taniSu">2単位</div><div class="signClass"></div><div><button></button></div></div>"""


def test_live_observed_grid_with_multiple_days_and_intensive_course():
    page = BeautifulSoup(
        """<h3>2026年度 後期時間割</h3><table><thead><tr><th></th><th>月曜日</th><th>火曜日</th></tr></thead>
    <tbody><tr><td>1</td><td>"""
        + BLOCK
        + "</td><td>"
        + BLOCK
        + """</td></tr></tbody></table>
    <table><thead><tr><th>授業科目</th><th>教員氏名</th><th>教室</th><th>単位数</th></tr></thead>
    <tbody><tr><td>Synthetic intensive</td><td>Teacher</td><td></td><td>1</td></tr></tbody></table>""",
        "lxml",
    )
    rows = parse_timetable(page)
    assert len(rows) == 3
    assert [r["weekday"] for r in rows] == [1, 2, None]
    assert rows[0]["semester"] == "後期" and rows[0]["year"] == "2026"
    assert rows[0]["classroom"] == "Campus Room"
    assert rows[2]["schedule_type"] == "intensive" and rows[2]["classroom"] is None


def test_timetable_unknown_course_cell_fails():
    page = BeautifulSoup(
        """<table><thead><tr><th></th><th>月曜日</th></tr></thead>
        <tbody><tr><td>1</td><td>Changed layout</td></tr></tbody></table>""",
        "lxml",
    )
    with pytest.raises(StructureChanged):
        parse_timetable(page)


def test_timetable_query_date_is_weekly_pattern(monkeypatch):
    monkeypatch.setattr(
        server,
        "_dataset",
        lambda *args: {
            "items": [{"weekday": 1, "semester": "後期"}, {"weekday": 2, "semester": "後期"}],
            "fetched_at": "2026-11-10T00:00:00+00:00",
            "source": "https://portal.chibatech.ac.jp/",
        },
    )

    async def check():
        result = await server.portal_query(kind="timetable", on_date="2026-11-09", semester="後期")
        assert len(result.items) == 1
        assert result.date_semantics == "weekly_pattern_only"
        result = await server.portal_query(kind="timetable", on_date="2026-11-09", weekday=2)
        assert result.is_error and result.structured_content["error"]["code"] == "INVALID_INPUT"

    anyio.run(check)
