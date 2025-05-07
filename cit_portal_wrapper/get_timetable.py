# Author: issa06

from bs4 import BeautifulSoup
import json
import re
from . import portal_wrapper


class Timetableboard:
    def __init__(self, top_page: portal_wrapper.TopPage):
        self.ses = top_page.ses
        self.top_page = top_page
        self.soup = self.load()

        self.func_form = self.soup.select_one("form#funcForm")
        self.func_data = {
            t.get("name"): t.get("value", "")
            for t in self.func_form.select('input[type="hidden"]')
        }
        self.rx_data = {k: v for k, v in self.func_data.items() if k.startswith("rx-")}

    def load(self):
        menu_form = self.top_page.soup.select_one("form#menuForm")
        data = {
            t.get("name", ""): t.get("value", "")
            for t in menu_form.select('input[type="hidden"]')
        }
        data.update(
            {
                "rx.sync.source": "menuForm:mainMenu",
                "menuForm:mainMenu": "menuForm:mainMenu",
                "menuForm:mainMenu_menuid": "2_0_0_0",
            }
        )
        response = self.ses.post(
            "https://portal.it-chiba.ac.jp/uprx/up/bs/bsa001/Bsa00101.xhtml", data
        )
        soup = BeautifulSoup(response.content, "xml")
        return soup

    def parse_subject(self, subject):
        # subjectから授業番号、授業名、教員名を分割
        m = re.match(r"^(\d+)(.*?)（(.+?)）$", subject)
        if m:
            course_number = m.group(1)
            course_name = m.group(2).strip()
            teacher_name = m.group(3).strip()
            return course_number, course_name, teacher_name
        return None, subject, None

    def get_timetable(self):
        table = self.soup.select_one("div.attendanceInfo table")
        if not table:
            raise Exception("出欠状況のテーブルが見つかりません。")

        data = []
        rows = table.select("tbody tr")
        for row in rows:
            cells = row.find_all("td")
            if len(cells) < 2:
                continue
            day_slot = cells[0].get_text(strip=True)
            subject_text = cells[1].get_text(strip=True)
            # subject_textについて、授業番号、授業名、教員名に分割
            course_number, course_name, teacher_name = self.parse_subject(subject_text)
            records = []
            for cell in cells[2:]:
                status_elem = cell.find("span", class_="syuketsuKbnMark")
                status = status_elem.get_text(strip=True) if status_elem else ""
                date_elem = cell.find("p", class_="jugyoDate")
                date_text = date_elem.get_text(strip=True) if date_elem else ""
                records.append({"status": status, "date": date_text})
            data.append(
                {
                    "day_slot": day_slot,
                    "course_number": course_number,
                    "couese_name": course_name,
                    "teacher_name": teacher_name,
                    "records": records,
                }
            )
        return data


def get_attendance_json(user_id: str, password: str):
    top_page = portal_wrapper.TopPage(user_id, password)
    board = Timetableboard(top_page)
    timetable = (
        board.get_timetable()
    )
    with open("timetable.json", "w", encoding="utf-8") as f:
        json.dump(timetable, f, ensure_ascii=False, indent=4)

    return timetable
