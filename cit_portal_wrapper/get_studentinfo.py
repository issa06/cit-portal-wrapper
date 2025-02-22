# Author: issa06

from bs4 import BeautifulSoup
import json
from . import portal_wrapper


class InfoPage:
    def __init__(self, top_page: portal_wrapper.TopPage):
        self.ses = top_page.ses
        self.top_page = top_page
        self.soup = self.load_info_page()

    def load_info_page(self):
        menu_form = self.top_page.soup.select_one("form#menuForm")
        if menu_form is None:
            raise Exception("メニュー画面が見つかりません")
        data = {
            t.get("name", ""): t.get("value", "")
            for t in menu_form.select('input[type="hidden"]')
        }
        data.update(
            {
                "rx.sync.source": "menuForm:mainMenu",
                "menuForm:mainMenu": "menuForm:mainMenu",
                "menuForm:mainMenu_menuid": "0_1_0_0",
            }
        )
        url = "https://portal.it-chiba.ac.jp/uprx/up/bs/bsa001/Bsa00101.xhtml"
        response = self.ses.post(url, data=data)
        soup = BeautifulSoup(response.content, "lxml")
        return soup

    def parse_inner_table(self, panel_div):
        inner_table = panel_div.select_one("td.dataStyle > table")
        if not inner_table:
            return None
        items = {}
        for row in inner_table.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) < 2:
                continue
            key = cells[0].get_text(strip=True)
            value_list = list(cells[1].stripped_strings)
            value = value_list[0] if len(value_list) == 1 else value_list
            items[key] = value
        img_tags = panel_div.find_all(
            "img", src=lambda s: s and s.startswith("data:image/")
        )
        if img_tags:
            img_list = [img.get("src") for img in img_tags]
            items["顔写真"] = img_list[0] if len(img_list) == 1 else img_list
        return items

    def parse_datatable(self, panel_div):
        datatable = panel_div.select_one("table[role='grid']")
        if not datatable:
            return None
        thead = datatable.find("thead")
        tbody = datatable.find("tbody")
        if not (thead and tbody):
            return None
        header_cells = thead.find_all("th")
        col_names = [th.get_text(strip=True) for th in header_cells]
        data = []
        for row in tbody.find_all("tr"):
            cells = row.find_all("td")
            row_data = {}
            for i, cell in enumerate(cells):
                if i < len(col_names):
                    texts = list(cell.stripped_strings)
                    value = texts[0] if len(texts) == 1 else texts
                    row_data[col_names[i]] = value
            data.append(row_data)
        return data

    def parse_panels(self):
        container = self.soup.find("div", id="funcForm:snsGrpPanel")
        if container is None:
            raise Exception("パネルが見つかりません")
        panels = {}
        headers = container.find_all("h3", class_="ui-accordion-header")
        for header in headers:
            title = header.get_text(strip=True)
            panel_div = header.find_next_sibling("div")
            if not panel_div:
                panels[title] = None
                continue
            inner_data = self.parse_inner_table(panel_div)
            if inner_data is not None:
                panels[title] = inner_data
            else:
                panels[title] = self.parse_datatable(panel_div)
        return panels


def get_info_json(user_id, password):
    top_page = portal_wrapper.TopPage(user_id, password)
    info_page = InfoPage(top_page)
    student_info = (info_page.parse_panels())

    with open("basic_info.json", "w", encoding="utf-8") as f:
        json.dump(student_info, f, ensure_ascii=False, indent=4)

    return student_info
