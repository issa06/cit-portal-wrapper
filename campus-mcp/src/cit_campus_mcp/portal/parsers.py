from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from typing import Any

from bs4 import BeautifulSoup

from .client import PortalTopPage


def normalize_text(text: str | None) -> str | None:
    if text is None:
        return None
    return unicodedata.normalize("NFKC", text.replace("　", " ")).strip()


def _form_state(soup: BeautifulSoup) -> tuple[dict[str, str], dict[str, str]]:
    form = soup.select_one("form#funcForm")
    if form is None:
        return {}, {}
    data = {
        tag.get("name"): tag.get("value", "")
        for tag in form.select('input[type="hidden"]')
        if tag.get("name")
    }
    rx_data = {k: v for k, v in data.items() if k.startswith("rx-")}
    return data, rx_data


def get_notices(top: PortalTopPage, full: bool = False) -> list[dict[str, Any]]:
    soup = top.menu_post("0_3_0_0")
    if full:
        # Full-board navigation differs by deployment. Keep the safe summary page if controls are absent.
        tab = soup.select_one('.ui-tabs-panel:nth-child(2)')
        button = tab.select_one('button[title*="すべての掲示を表示"]') if tab else None
        if button and button.get("id"):
            func_data, rx_data = _form_state(soup)
            button_id = button.get("id")
            post_data = {
                **func_data,
                **rx_data,
                "javax.faces.partial.ajax": "true",
                "javax.faces.source": button_id,
                "javax.faces.partial.execute": "@all",
                "javax.faces.partial.render": "funcForm",
                button_id: button_id,
            }
            response = top.session.post(
                top.config.app_base.rstrip("/") + "/uprx/up/bs/bsd007/Bsd00701.xhtml",
                data=post_data,
                timeout=top.config.timeout,
            )
            if response.ok:
                soup = BeautifulSoup(response.content, "lxml")

    panel = soup.select_one(".ui-tabs-panel:nth-child(2)") or soup
    notices: list[dict[str, Any]] = []
    for item in panel.select("#keiji"):
        title_tag = item.select_one("a")
        if title_tag is None:
            continue
        raw_date = title_tag.next_sibling.strip() if isinstance(title_tag.next_sibling, str) else ""
        parsed_date = None
        try:
            parsed_date = datetime.strptime(raw_date, "%Y/%m/%d").date().isoformat()
        except ValueError:
            parsed_date = raw_date or None
        category_tag = item.select_one("span.keijiCategory")
        notices.append(
            {
                "important": not bool(item.select_one("i.fa-exclamation-circle.hiddenStyle")),
                "unread_or_highlighted": not bool(item.select_one("i.fa-lightbulb-circle.hiddenStyle")),
                "category": category_tag.get_text(strip=True) if category_tag else None,
                "title": title_tag.get_text(strip=True),
                "date": parsed_date,
            }
        )
    return notices


def _update_grade_markers(row, markers: dict[str, Any]) -> bool:
    level2 = row.find("td", class_=lambda x: x and "kamokuLevel2" in x)
    if level2:
        markers["course_category"] = level2.get_text(strip=True)
        return True
    level3 = row.find("td", class_=lambda x: x and "kamokuLevel3" in x)
    if level3:
        markers["classification"] = level3.get_text(strip=True)
        return True
    level4 = row.find("td", class_=lambda x: x and "kamokuLevel4" in x)
    if level4:
        value = level4.get_text(strip=True)
        markers["requirement"] = True if value == "【必修】" else False if value == "【選択】" else None
        return True
    return False


def get_grades(top: PortalTopPage) -> list[dict[str, Any]]:
    soup = top.menu_post("2_1_0_5")
    grades: list[dict[str, Any]] = []
    index = 0
    while True:
        grades_div = soup.select_one(f"div#funcForm\\:j_idt181\\:{index}\\:sskList")
        if grades_div is None:
            break
        year_tag = soup.select_one(f"#funcForm\\:j_idt181\\:{index}\\:nendo")
        semester_tag = soup.select_one(f"#funcForm\\:j_idt181\\:{index}\\:gakki")
        year = year_tag.get_text(strip=True) if year_tag else "不明"
        semester = semester_tag.get_text(strip=True) if semester_tag else "不明"
        tbody = grades_div.select_one("tbody")
        markers: dict[str, Any] = {"course_category": None, "classification": None, "requirement": None}
        if tbody:
            for row in tbody.find_all("tr"):
                if _update_grade_markers(row, markers):
                    continue
                cells = row.find_all("td")
                if len(cells) < 7:
                    continue
                subject = normalize_text(cells[1].get_text(strip=True)) or ""
                if not subject or subject == "総単位":
                    continue
                if any(k in subject for k in ("中学校教諭", "高等学校教諭")):
                    break
                credits = normalize_text(cells[2].get_text(strip=True))
                evaluation = normalize_text(cells[3].get_text(strip=True)) or "履修中"
                gpa_target = (normalize_text(cells[4].get_text(strip=True)) == "○")
                teacher = normalize_text(cells[6].get_text(strip=True))
                grades.append(
                    {
                        "year": year,
                        "semester": semester,
                        "course_category": normalize_text(markers.get("course_category")),
                        "classification": normalize_text(markers.get("classification")),
                        "requirement": markers.get("requirement"),
                        "subject": subject,
                        "credits": credits,
                        "evaluation": evaluation,
                        "gpa_target": gpa_target,
                        "teacher": teacher,
                    }
                )
        index += 1
    if not grades:
        raise RuntimeError("No grade rows were found. The Portal DOM may have changed or the page is unavailable.")
    return grades


def _parse_course_label(subject: str) -> tuple[str | None, str, str | None]:
    match = re.match(r"^(\d+)(.*?)（(.+?)）$", subject)
    if match:
        return match.group(1), match.group(2).strip(), match.group(3).strip()
    return None, subject, None


def _parse_attendance_table(soup: BeautifulSoup) -> list[dict[str, Any]]:
    table = soup.select_one("div.attendanceInfo table")
    if table is None:
        raise RuntimeError("Attendance/timetable table was not found.")
    result: list[dict[str, Any]] = []
    for row in table.select("tbody tr"):
        cells = row.find_all("td")
        if len(cells) < 2:
            continue
        day_slot = cells[0].get_text(strip=True)
        course_number, course_name, teacher_name = _parse_course_label(cells[1].get_text(strip=True))
        records = []
        for cell in cells[2:]:
            status_tag = cell.find("span", class_="syuketsuKbnMark")
            date_tag = cell.find("p", class_="jugyoDate")
            records.append(
                {
                    "status": status_tag.get_text(strip=True) if status_tag else "",
                    "date": date_tag.get_text(strip=True) if date_tag else "",
                }
            )
        result.append(
            {
                "day_slot": day_slot,
                "course_number": course_number,
                "course_name": course_name,
                "teacher_name": teacher_name,
                "records": records,
            }
        )
    return result


def get_attendance(top: PortalTopPage) -> list[dict[str, Any]]:
    return _parse_attendance_table(top.menu_post("2_1_0_4"))


def get_timetable(top: PortalTopPage) -> list[dict[str, Any]]:
    # This menu is retained from the existing fork. Some Portal deployments expose
    # attendance-like records here instead of a pure weekly timetable.
    return _parse_attendance_table(top.menu_post("2_0_0_0"))


def get_student_info(top: PortalTopPage, include_photo: bool = False) -> dict[str, Any]:
    soup = top.menu_post("0_1_0_0")
    container = soup.find("div", id="funcForm:snsGrpPanel")
    if container is None:
        raise RuntimeError("Student information panels were not found.")
    panels: dict[str, Any] = {}
    for header in container.find_all("h3", class_="ui-accordion-header"):
        title = header.get_text(strip=True)
        panel = header.find_next_sibling("div")
        if panel is None:
            panels[title] = None
            continue
        inner = panel.select_one("td.dataStyle > table")
        if inner:
            items: dict[str, Any] = {}
            for row in inner.find_all("tr"):
                cells = row.find_all("td")
                if len(cells) < 2:
                    continue
                key = cells[0].get_text(strip=True)
                values = list(cells[1].stripped_strings)
                items[key] = values[0] if len(values) == 1 else values
            if include_photo:
                image = panel.find("img", src=lambda s: s and str(s).startswith("data:image/"))
                if image:
                    items["顔写真"] = image.get("src")
            panels[title] = items
            continue
        table = panel.select_one("table[role='grid']")
        if table and table.thead and table.tbody:
            columns = [th.get_text(strip=True) for th in table.thead.find_all("th")]
            rows = []
            for row in table.tbody.find_all("tr"):
                values = []
                for cell in row.find_all("td"):
                    strings = list(cell.stripped_strings)
                    values.append(strings[0] if len(strings) == 1 else strings)
                rows.append({name: values[i] if i < len(values) else None for i, name in enumerate(columns)})
            panels[title] = rows
        else:
            panels[title] = panel.get_text(" ", strip=True)
    return panels
