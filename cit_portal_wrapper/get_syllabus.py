# Author: issa06

import os
import re

from bs4 import BeautifulSoup

from . import portal_wrapper


class SyllabusPage:
    def __init__(self, top_page: portal_wrapper.TopPage):
        self.ses = top_page.ses
        self.top_page = top_page
        self.soup = self.load_syllabus_page()

    def load_syllabus_page(self):
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
                "menuForm:mainMenu_menuid": "2_0_0_2",
            }
        )
        url = "https://portal.it-chiba.ac.jp/uprx/up/bs/bsa001/Bsa00101.xhtml"
        response = self.ses.post(url, data=data)
        soup = BeautifulSoup(response.content, "xml")
        return soup

    def search_syllabus(self, keyword=None, year=None, faculty=None, teacher=None,
                        campus=None, day=None, period=None, subject=None):
        """シラバス検索機能

        Args:
            keyword (str, optional): 検索キーワード
            year (str, optional): 開講年度（例: "2025"）
            faculty (str, optional): 学科組織（例: "1" 学部全体, "10" 工学部）
            teacher (str, optional): 担当教員名
            campus (str, optional): キャンパス（"1"=津田沼, "2"=新習志野）
            day (list, optional): 曜日 (["1","2"]など 1=月, 2=火, ...)
            period (list, optional): 時限 (["1","2"]など 1=1限, 2=2限, ...)
            subject (str, optional): 授業科目名

        Returns:
            list: 検索結果のリスト
        """
        try:
            # シラバス検索ページに移動
            search_url = "/uprx/up/km/kmh006/Kmh00601.xhtml"
            response = self.ses.get(
                f"https://portal.it-chiba.ac.jp{search_url}")

            print(f"シラバス検索ページステータスコード: {response.status_code}")

            # デバッグ用にHTMLの一部を保存
            if os.environ.get("DEBUG"):
                with open("syllabus_search_page.html", "w", encoding="utf-8") as f:
                    f.write(response.text[:10000])  # 最初の10000文字を保存

            soup = BeautifulSoup(response.text, "html.parser")

            # フォームの存在確認
            form = soup.select_one("form#funcForm")
            if not form:
                print("警告: シラバス検索フォームが見つかりません")
                print("利用可能なフォーム:")
                for f in soup.select("form"):
                    print(f"  - ID: {f.get('id')}, Name: {f.get('name')}")

            # トークン情報を取得
            token_input = soup.select_one("input[name='rx-token']")
            if not token_input:
                raise Exception(
                    "シラバス検索ページでトークン情報が見つかりません。ポータルサイトの仕様が変更された可能性があります。")

            token = token_input["value"]

            # ログインキーを取得
            login_key_input = soup.select_one("input[name='rx-loginKey']")
            if not login_key_input:
                raise Exception("ログインキーが見つかりません")
            login_key = login_key_input["value"]

            # ViewStateを取得
            view_state_input = soup.select_one(
                "input[name='javax.faces.ViewState']")
            if not view_state_input:
                raise Exception("ViewStateが見つかりません")
            view_state = view_state_input["value"]

            # 検索フォームを構築
            form_data = {
                "funcForm": "funcForm",
                "rx-token": token,
                "rx-loginKey": login_key,
                "rx-deviceKbn": "1",
                "rx-loginType": "Gakuen",
                "funcForm:j_idt174_input": "on",  # 英語表示
                "javax.faces.ViewState": view_state
            }

            # 検索条件を追加
            if year:
                form_data["funcForm:kaikoNendo_input"] = year
            else:
                form_data["funcForm:kaikoNendo_input"] = "2025"  # デフォルト値

            # 前期/後期の指定
            form_data["funcForm:kaikoGakki_input"] = "01"  # デフォルト: 前期

            if keyword:
                form_data["funcForm:keyword"] = keyword

            if subject:
                form_data["funcForm:jugyoKamoku"] = subject

            if faculty:
                form_data["funcForm:cgksSearchType0_input"] = faculty

            if teacher:
                form_data["funcForm:tantoKyoin"] = teacher

            if campus:
                form_data["funcForm:campus_input"] = campus

            # 曜日と時限のチェックボックス
            if day:
                for d in day:
                    form_data[f"funcForm:yobiList_{int(d)-1}"] = d

            if period:
                for p in period:
                    form_data[f"funcForm:jigenList_{int(p)-1}"] = p

            # 検索ボタンのリクエストパラメータ
            form_data["funcForm:search"] = "funcForm:search"

            # POSTリクエストで検索を実行
            headers = {
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": f"https://portal.it-chiba.ac.jp{search_url}"
            }
            print("検索リクエストを送信します...")
            response = self.ses.post(
                f"https://portal.it-chiba.ac.jp{search_url}", data=form_data, headers=headers)
            print(f"検索結果ステータスコード: {response.status_code}")

            # デバッグ用に検索結果ページを保存
            if os.environ.get("DEBUG"):
                with open("search_results.html", "w", encoding="utf-8") as f:
                    f.write(response.text[:10000])

            result_soup = BeautifulSoup(response.text, "html.parser")

            # 検索結果をパース
            results = []
            result_table = result_soup.select_one("table.ui-datatable-data")

            if not result_table:
                print("警告: 検索結果テーブルが見つかりません")
                # 利用可能なテーブルを確認
                tables = result_soup.select("table")
                print(f"ページ内のテーブル数: {len(tables)}")
                for i, table in enumerate(tables):
                    print(f"テーブル {i+1} クラス: {table.get('class')}")

                # エラーメッセージの確認
                error_msg = result_soup.select_one(".ui-messages-error")
                if error_msg:
                    print(f"エラーメッセージ: {error_msg.get_text(strip=True)}")

                return []  # 空のリストを返す

            rows = result_table.select("tr")
            for row in rows:
                cells = row.select("td")
                if not cells:
                    continue

                subject_data = {
                    "科目名": cells[0].get_text(strip=True) if len(cells) > 0 else "",
                    "科目ナンバリング": cells[1].get_text(strip=True) if len(cells) > 1 else "",
                    "担当教員": cells[2].get_text(strip=True) if len(cells) > 2 else "",
                    "開講年度": cells[3].get_text(strip=True) if len(cells) > 3 else "",
                    "曜日・時限": cells[4].get_text(strip=True) if len(cells) > 4 else "",
                    "単位数": cells[5].get_text(strip=True) if len(cells) > 5 else "",
                    "キャンパス": cells[6].get_text(strip=True) if len(cells) > 6 else "",
                }

                # シラバス詳細へのリンク
                detail_link = row.select_one("a[id*='syllabus']")
                if detail_link:
                    subject_data["detail_link"] = detail_link.get("id", "")

                results.append(subject_data)

            return results

        except Exception as e:
            print(f"シラバス検索中にエラーが発生しました: {str(e)}")
            raise

    def get_syllabus_detail(self, detail_link):
        """シラバス詳細情報を取得

        Args:
            detail_link (str): 詳細ページへのリンクID

        Returns:
            dict: シラバスの詳細情報
        """
        # TODO: シラバス詳細取得機能の実装
        pass
