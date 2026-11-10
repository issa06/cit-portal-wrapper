from bs4 import BeautifulSoup

from cit_campus_mcp.portal.parsers import _parse_attendance_table, normalize_text


def test_normalize_text():
    assert normalize_text("ＡＢＣ　１２３") == "ABC 123"


def test_attendance_parser_course_name_key():
    soup = BeautifulSoup(
        """
        <div class="attendanceInfo"><table><tbody>
          <tr>
            <td>水3</td><td>12345オペレーティングシステム（前川 仁孝）</td>
            <td><span class="syuketsuKbnMark">出</span><p class="jugyoDate">9/23</p></td>
          </tr>
        </tbody></table></div>
        """,
        "lxml",
    )
    rows = _parse_attendance_table(soup)
    assert rows[0]["course_number"] == "12345"
    assert rows[0]["course_name"] == "オペレーティングシステム"
    assert "couese_name" not in rows[0]
