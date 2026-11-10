from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from typing import Any

from bs4 import BeautifulSoup

from ..errors import DataUnavailable, ResponseTooLarge, StructureChanged
from ..webforms import portal_page
from .client import PortalTopPage
from .notices import notice_read_state, notice_reference


def normalize_text(text: str | None) -> str | None:
    if text is None:
        return None
    return unicodedata.normalize("NFKC", text.replace("　", " ")).strip()


def _form_state(soup: BeautifulSoup) -> tuple[dict[str, str], dict[str, str]]:
    form = soup.select_one("form#funcForm")
    if form is None:
        return {}, {}
    data = {tag.get("name"): tag.get("value", "") for tag in form.select('input[type="hidden"]') if tag.get("name")}
    rx_data = {k: v for k, v in data.items() if k.startswith("rx-")}
    return data, rx_data


def get_notices(top: PortalTopPage, full: bool = False) -> list[dict[str, Any]]:
    notices = []
    seen = set()
    for soup in iter_notice_pages(top, full):
        for row in parse_notices(soup):
            identity = (row["date"], row["category"], row["title"])
            if identity not in seen:
                seen.add(identity)
                notices.append(row)
    return notices


def iter_notice_pages(top: PortalTopPage, full: bool = False):
    """Yield live pages so selection never uses a component ID from a stale page."""
    soup = top.menu_post("0_3_0_0")
    if full:
        # Full-board navigation differs by deployment. Keep the safe summary page if controls are absent.
        button = soup.select_one('button[title*="すべての掲示を表示"]')
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
            soup = portal_page(response)

    seen = set()
    page_signatures = set()
    for page in range(20):
        rows = parse_notices(soup)
        signature = repr(rows)
        if signature in page_signatures:
            raise StructureChanged("Notice pagination repeated a page.")
        page_signatures.add(signature)
        for row in rows:
            identity = (row["date"], row["category"], row["title"])
            if identity not in seen:
                seen.add(identity)
        if len(seen) > 2000:
            raise ResponseTooLarge("Notice traversal limit reached.")
        yield soup
        next_button = soup.select_one(
            '.ui-paginator-next:not(.ui-state-disabled), button[title="次へ"]:not([disabled])'
        )
        if not full or next_button is None:
            return
        data, _ = _form_state(soup)
        source = next_button.get("id") or next_button.get("name")
        if not source:
            paginator = next_button.find_parent(class_="ui-paginator")
            paginator_id = str(paginator.get("id", "")) if paginator else ""
            source = re.sub(r"_paginator_(top|bottom)$", "", paginator_id)
            if not source or source == paginator_id:
                raise StructureChanged("Notice pagination control is unsupported.")
            size_tag = soup.select_one("select.ui-paginator-rpp-options option[selected]")
            size = int(size_tag.get("value")) if size_tag and str(size_tag.get("value", "")).isdigit() else len(rows)
            if size < 1:
                raise StructureChanged("Notice page size is unavailable.")
            data.update(
                {source + "_pagination": "true", source + "_first": str((page + 1) * size), source + "_rows": str(size)}
            )
        data.update(
            {
                "javax.faces.partial.ajax": "true",
                "javax.faces.source": source,
                "javax.faces.partial.execute": "@all",
                "javax.faces.partial.render": "funcForm",
                source: source,
            }
        )
        response = top.session.post(
            top.config.app_base.rstrip("/") + "/uprx/up/bs/bsd007/Bsd00701.xhtml", data=data, timeout=top.config.timeout
        )
        soup = portal_page(response)
    raise ResponseTooLarge("Notice page limit reached; refine the request.")


def parse_notices(soup: BeautifulSoup) -> list[dict[str, Any]]:
    panel = soup
    if not panel.select("#keiji"):
        if any(
            t in panel.get_text(" ", strip=True)
            for t in ("掲示はありません", "掲示情報はありません", "該当するデータがありません")
        ):
            return []
        raise StructureChanged("Notice list was not found.")
    notices: list[dict[str, Any]] = []
    for item in panel.select("#keiji"):
        title_tag = item.select_one("a")
        if title_tag is None:
            raise StructureChanged("Notice title was not found.")
        date_match = re.search(r"\d{4}/\d{1,2}/\d{1,2}", item.get_text(" ", strip=True))
        raw_date = date_match.group() if date_match else ""
        parsed_date = None
        try:
            parsed_date = datetime.strptime(raw_date, "%Y/%m/%d").date().isoformat()
        except ValueError:
            parsed_date = raw_date or None
        category_tag = item.select_one("span.keijiCategory")
        record = {
            "important": ("hiddenStyle" not in item.select_one("i.fa-exclamation-circle").get("class", []))
            if item.select_one("i.fa-exclamation-circle")
            else None,
            "unread_or_highlighted": ("hiddenStyle" not in item.select_one("i.fa-lightbulb-circle").get("class", []))
            if item.select_one("i.fa-lightbulb-circle")
            else None,
            "category": normalize_text(category_tag.get_text(strip=True)) if category_tag else None,
            "title": normalize_text(title_tag.get_text(strip=True)),
            "date": parsed_date,
            "read_state": notice_read_state(title_tag),
        }
        record["notice_ref"] = notice_reference(record, str(title_tag.get("id", "")))
        notices.append(record)
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
    for grades_div in soup.select('div[id$=":sskList"]'):
        prefix = grades_div.get("id").rsplit(":", 1)[0]
        year_tag = soup.find(id=prefix + ":nendo")
        semester_tag = soup.find(id=prefix + ":gakki")
        year = year_tag.get_text(strip=True) if year_tag else None
        semester = semester_tag.get_text(strip=True) if semester_tag else None
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
                evaluation = normalize_text(cells[3].get_text(strip=True)) or None
                gpa_raw = normalize_text(cells[4].get_text(strip=True))
                gpa_target = True if gpa_raw in {"○", "◯"} else False if gpa_raw in {"×", "対象外"} else None
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
                        "publication_status": "unpublished"
                        if evaluation in {None, "未公開"}
                        else "pending"
                        if evaluation in {"未確定", "未公開", "履修中"}
                        else "reported",
                        "gpa_target": gpa_target,
                        "teacher": teacher,
                    }
                )
    if not grades:
        text = soup.get_text(" ", strip=True)
        if any(t in text for t in ("成績は未公開", "成績は公開されていません", "公開期間外")):
            raise DataUnavailable("Grades have not been published.")
        if "該当するデータがありません" not in text:
            raise StructureChanged("Grade rows were not found.")
    return grades


def _parse_course_label(subject: str) -> tuple[str | None, str, str | None]:
    match = re.match(r"^(\d+)(.*?)[（(](.+?)[）)]$", subject)
    if match:
        return match.group(1), match.group(2).strip(), match.group(3).strip()
    return None, subject, None


def _parse_attendance_table(soup: BeautifulSoup) -> list[dict[str, Any]]:
    table = soup.select_one("div.attendanceInfo table")
    if table is None:
        raise StructureChanged("Attendance table was not found.")
    result: list[dict[str, Any]] = []
    for row in table.select("tbody tr"):
        cells = row.find_all("td")
        if len(cells) < 2:
            if "該当するデータがありません" in row.get_text():
                continue
            raise StructureChanged("Attendance row has missing columns.")
        day_slot = cells[0].get_text(strip=True)
        course_number, course_name, teacher_name = _parse_course_label(cells[1].get_text(strip=True))
        records = []
        for cell in cells[2:]:
            status_tag = cell.find("span", class_="syuketsuKbnMark")
            date_tag = cell.find("p", class_="jugyoDate")
            records.append(
                {
                    "status": status_tag.get_text(strip=True) if status_tag else None,
                    "normalized_status": {
                        "出": "present",
                        "出席": "present",
                        "欠": "absent",
                        "欠席": "absent",
                        "遅": "late",
                        "遅刻": "late",
                        "公": "excused",
                        "公欠": "excused",
                        "早": "early_leave",
                        "早退": "early_leave",
                    }.get(status_tag.get_text(strip=True))
                    if status_tag
                    else None,
                    "date": date_tag.get_text(strip=True) if date_tag else None,
                }
            )
        result.append(
            {
                "day_slot": day_slot,
                "course_number": course_number,
                "course_name": course_name,
                "teacher_name": teacher_name,
                "records": records,
                "computed_summary": {
                    status: sum(r["normalized_status"] == status for r in records)
                    for status in ("present", "absent", "late", "excused", "early_leave")
                },
                "missing_status_count": sum(r["normalized_status"] is None for r in records),
                "summary_source": "local_record_count",
            }
        )
    return result


def get_attendance(top: PortalTopPage) -> list[dict[str, Any]]:
    return _parse_attendance_table(top.menu_post("2_1_0_4"))


def get_timetable(top: PortalTopPage) -> list[dict[str, Any]]:
    return parse_timetable(top.menu_post("2_0_0_0"))


def _table_term(table) -> tuple[str | None, str | None]:
    # Use an explicit heading supplied by the portal; never infer a university term
    # from the Mac's calendar month or from a course title.
    for tag in table.find_all_previous(["h1", "h2", "h3", "h4", "legend", "span"]):
        text = normalize_text(tag.get_text(" ", strip=True)) or ""
        match = re.fullmatch(r"(?:(20\d{2})年度?\s*)?(前期|後期|春学期|秋学期)(?:\s*時間割)?", text)
        if match:
            return match[1], match[2]
    return None, None


def parse_timetable(soup: BeautifulSoup) -> list[dict[str, Any]]:
    """Observed UPRX weekly grids and header-labelled intensive-course tables.

    Preserve each weekday/period occurrence; do not deduplicate a multi-slot course.
    No registration, syllabus or detail buttons are clicked.
    """
    result = []
    recognized = False
    for table in soup.find_all("table"):
        headers = table.select("thead th")
        labels = [normalize_text(h.get_text(" ", strip=True)) or "" for h in headers]
        days = [
            next((i + 1 for i, d in enumerate("月火水木金土日") if re.fullmatch(d + r"曜(?:日)?", text)), None)
            for text in labels
        ]
        year, semester = _table_term(table)
        if any(days):
            recognized = True
            for row in table.select("tbody > tr"):
                cells = row.find_all("td", recursive=False)
                if not cells:
                    continue
                if len(cells) != len(days):
                    raise StructureChanged("Timetable grid column layout changed.")
                period_text = normalize_text(cells[0].get_text(strip=True)) or ""
                period = int(period_text) if period_text.isdigit() else None
                for index, weekday in enumerate(days):
                    if weekday is None:
                        continue
                    cell = cells[index]
                    for subject in cell.select(".fontB"):
                        block = subject.parent
                        fields = block.find_all("div", recursive=False)
                        # Verified on the live UPRX grid: subject, teacher, room,
                        # credits, signs, action buttons. Fail rather than guess.
                        if len(fields) < 5 or fields[0] != subject or "taniSu" not in fields[3].get("class", []):
                            raise StructureChanged("Timetable course block layout changed.")
                        name = normalize_text(subject.get_text(" ", strip=True))
                        if not name:
                            raise StructureChanged("Timetable course name is missing.")
                        result.append(
                            {
                                "year": year,
                                "semester": semester,
                                "weekday": weekday,
                                "period": period,
                                "day_slot": "月火水木金土日"[weekday - 1] + period_text,
                                "course_name": name,
                                "teacher_name": normalize_text(fields[1].get_text(" ", strip=True)) or None,
                                "classroom": normalize_text(fields[2].get_text(" ", strip=True)) or None,
                                "credits": normalize_text(fields[3].get_text(" ", strip=True)) or None,
                                "schedule_type": "weekly",
                            }
                        )
                    if cell.get_text(strip=True) and not cell.select(".fontB"):
                        # A populated course cell with an unknown structure is a
                        # parser failure, not an empty weekly slot.
                        raise StructureChanged("Timetable course cell layout changed.")
        elif "授業科目" in labels and "教員氏名" in labels and "教室" in labels:
            recognized = True
            for row in table.select("tbody > tr"):
                cells = row.find_all("td", recursive=False)
                if len(cells) == 1 and "該当するデータがありません" in cells[0].get_text():
                    continue
                if len(cells) != len(labels):
                    raise StructureChanged("Intensive-course table layout changed.")
                values = {
                    label: normalize_text(cell.get_text(" ", strip=True)) or None for label, cell in zip(labels, cells)
                }
                if not values.get("授業科目"):
                    continue
                result.append(
                    {
                        "year": year,
                        "semester": semester,
                        "weekday": None,
                        "period": None,
                        "day_slot": None,
                        "course_name": values["授業科目"],
                        "teacher_name": values["教員氏名"],
                        "classroom": values["教室"],
                        "credits": values.get("単位数"),
                        "schedule_type": "intensive",
                    }
                )
    if not recognized:
        raise StructureChanged("Weekly timetable grids were not found.")
    return result


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
