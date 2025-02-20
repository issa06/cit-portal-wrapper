# Author: issa06

from bs4 import BeautifulSoup
import json
import cit_portal_wrapper.portal_wrapper as portal_wrapper


class Gradeboard:
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
                "menuForm:mainMenu_menuid": "2_1_0_5",
            }
        )
        response = self.ses.post(
            "https://portal.it-chiba.ac.jp/uprx/up/bs/bsa001/Bsa00101.xhtml", data
        )
        soup = BeautifulSoup(response.content, "xml")
        return soup

    def get_max_section_index(self):
        # 成績表のセクション数を取得する関数
        max_index = 0
        while True:
            div_id = f"div#funcForm\\:j_idt181\\:{max_index}\\:sskList"
            if not self.soup.select_one(div_id):
                break
            max_index += 1
        return max_index - 1

    def parse_section(self, index):
        # セクションの年度, 学期, 成績行を取得する関数
        year_id = f"#funcForm\\:j_idt181\\:{index}\\:nendo"
        semester_id = f"#funcForm\\:j_idt181\\:{index}\\:gakki"
        div_id = f"div#funcForm\\:j_idt181\\:{index}\\:sskList"

        year_elem = self.soup.select_one(year_id)
        semester_elem = self.soup.select_one(semester_id)
        year = year_elem.get_text(strip=True) if year_elem else "不明"
        semester = semester_elem.get_text(strip=True) if semester_elem else "不明"

        grades_div = self.soup.select_one(div_id)
        if not grades_div:
            return year, semester, []
        tbody = grades_div.select_one("tbody")
        if not tbody:
            return year, semester, []
        rows = tbody.find_all("tr")
        return year, semester, rows

    def update_markers(self, row, markers):
        # マーカーを更新用関数
        # マーカー行の場合はTrue, それ以外の場合はFalse
        td_level2 = row.find("td", class_=lambda x: x and "kamokuLevel2" in x)
        if td_level2:
            markers["course_category"] = td_level2.get_text(strip=True)
            return True

        td_level3 = row.find("td", class_=lambda x: x and "kamokuLevel3" in x)
        if td_level3:
            markers["classification"] = td_level3.get_text(strip=True)
            return True

        td_level4 = row.find("td", class_=lambda x: x and "kamokuLevel4" in x)
        if td_level4:
            text_val = td_level4.get_text(strip=True)
            if text_val == "【必修】":
                markers["requirement"] = True
            elif text_val == "【選択】":
                markers["requirement"] = False
            else:
                markers["requirement"] = text_val
            return True

        return False

    def parse_grade_row(self, row, markers, skip_keywords):
        # 成績行から成績情報を取得する関数
        cells = row.find_all("td")
        if len(cells) < 7:
            return None

        subject = cells[1].get_text(strip=True)
        if subject == "総単位":
            return None
        if any(keyword in subject for keyword in skip_keywords):
            return "BREAK"

        credits = cells[2].get_text(strip=True)
        evaluation = cells[3].get_text(strip=True)
        gpa_target_text = cells[4].get_text(strip=True)
        gpa_target = True if gpa_target_text == "○" else gpa_target_text
        # 出席率の取得は将来実装された時のためにコメントアウト
        # attendance = cells[5].get_text(strip=True)
        teacher = cells[6].get_text(strip=True)

        grade = {
            "course_category": markers.get("course_category"),
            "classification": markers.get("classification"),
            "requirement": markers.get("requirement"),
            "subject": subject,
            "credits": credits,
            "evaluation": evaluation,
            "gpa_target": gpa_target,
            "teacher": teacher,
        }
        return grade

    def get_grades(self):
        # 成績情報の整形を行う関数
        grades = []
        skip_keywords = ["中学校教諭", "高等学校教諭"]

        max_index = self.get_max_section_index()
        if max_index < 0:
            raise Exception("成績テーブルの div 要素が見つかりません。")

        for i in range(max_index + 1):
            year, semester, rows = self.parse_section(i)
            if not rows:
                continue

            markers = {
                "course_category": None,
                "classification": None,
                "requirement": None,
            }
            for row in rows:
                if self.update_markers(row, markers):
                    continue

                grade = self.parse_grade_row(row, markers, skip_keywords)
                if grade == "BREAK":
                    break
                if grade is not None:
                    grade["year"] = year
                    grade["semester"] = semester
                    grades.append(grade)

        if not grades:
            with open("debug_grade_page.html", "w", encoding="utf-8") as f:
                f.write(self.soup.prettify())
            raise Exception(
                "Couldn't find any grade rows.\n"
                "Check the debug_grade_page.html to see if the correct page was accessed."
            )

        return grades


def get_grades_json(user_id, password):
    top_page = portal_wrapper.TopPage(user_id, password)
    gradeboard = Gradeboard(top_page)
    grades = list(gradeboard.get_grades())

    with open("grades.json", "w", encoding="utf-8") as f:
        json.dump(grades, f, ensure_ascii=False, indent=4)

    return grades
