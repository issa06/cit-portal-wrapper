# Author: issa06

from bs4 import BeautifulSoup
import json
from . import portal_wrapper


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

    def get_grades(self):
        """
        成績テーブルの div 要素から成績情報を抽出する (最大の N を自動検出)
        特定のキーワード (中学校教諭, 高等学校教諭) を含む科目名が出たら次の年度に移る
        """
        grades = []
        skip_keywords = ["中学校教諭", "高等学校教諭"]

        max_n = 0
        while True:
            div_id = f"div#funcForm\\:j_idt181\\:{max_n}\\:sskList"
            if not self.soup.select_one(div_id):
                break
            max_n += 1
        max_n -= 1

        if max_n < 0:
            raise Exception("成績テーブルの div 要素が見つかりません。")

        for i in range(max_n + 1):
            year_id = f"#funcForm\\:j_idt181\\:{i}\\:nendo"
            semester_id = f"#funcForm\\:j_idt181\\:{i}\\:gakki"
            div_id = f"div#funcForm\\:j_idt181\\:{i}\\:sskList"

            year_elem = self.soup.select_one(year_id)
            semester_elem = self.soup.select_one(semester_id)

            year = year_elem.get_text(strip=True) if year_elem else "不明"
            semester = semester_elem.get_text(strip=True) if semester_elem else "不明"

            grades_div = self.soup.select_one(div_id)

            if grades_div is None:
                continue

            tbody = grades_div.select_one("tbody")
            if not tbody:
                continue

            rows = tbody.find_all("tr")
            for row in rows:
                cells = row.find_all("td")
                if len(cells) < 7:
                    continue

                subject = cells[1].get_text(strip=True)  # 科目名

                if any(keyword in subject for keyword in skip_keywords):
                    break

                credits = cells[2].get_text(strip=True)  # 単位数
                evaluation = cells[3].get_text(strip=True)  # 評価
                gpa_target = cells[4].get_text(strip=True)  # GPA対象
                attendance = cells[5].get_text(strip=True)  # 出席率
                teacher = cells[6].get_text(strip=True)  # 教員氏名

                grades.append(
                    {
                        "year": year,
                        "semester": semester,
                        "subject": subject,
                        "credits": credits,
                        "evaluation": evaluation,
                        "gpa_target": gpa_target,
                        "attendance": attendance,
                        "teacher": teacher,
                    }
                )

        if not grades:
            with open("debug_grade_page.html", "w", encoding="utf-8") as f:
                f.write(self.soup.prettify())
            raise Exception(
                "Couldn't find any div elements.\n"
                "Check the debug_grade_page.html to see it accessed correct page."
            )

        return grades


def get_grades_json(user_id, password):
    top_page = portal_wrapper.TopPage(user_id, password)
    gradeboard = Gradeboard(top_page)
    grades = list(gradeboard.get_grades())

    with open("grades.json", "w", encoding="utf-8") as f:
        json.dump(grades, f, ensure_ascii=False, indent=4)

    return grades
