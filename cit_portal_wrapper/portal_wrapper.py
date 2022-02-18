#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import requests
from bs4 import BeautifulSoup
from datetime import datetime

class LoginError(Exception):
    pass


HEADERS = {
    'Content-Type': 'application/x-www-form-urlencoded',
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/69.0.3497.100'
}


class TopPage:
    def __init__(self, user_id, password):
        self.ses = requests.Session()
        self.ses.headers.update(HEADERS)
        self.soup = self.login(user_id, password)
    
    
    def login(self, user_id, password):
        login_form = {
            "loginForm": "loginForm",
            "loginForm:userId": user_id,
            "loginForm:password": password,
            "javax.faces.ViewState": "stateless",
            "loginForm:loginButton": ""
        }
        url = "https://portal.it-chiba.ac.jp/uprx/up/pk/pky001/Pky00101.xhtml"
        response = self.ses.post(url, login_form)
        soup = BeautifulSoup(response.content, 'lxml')
        if not soup.select_one('form#menuForm'):
            raise LoginError('ログイン失敗')
        return soup


class Noticeboard:
    def __init__(self, top_page:TopPage):
        self.ses = top_page.ses
        self.top_page = top_page
        self.soup = self.load()

        self.func_form = self.soup.select_one('form#funcForm')
        self.func_data = {t.get('name'): t.get('value', '') for t in self.func_form.select('input[type="hidden"]')}
        self.rx_data = {k: v for k, v in self.func_data.items() if k.startswith('rx-')}

    def load(self):
        menu_form = self.top_page.soup.select_one('form#menuForm')
        data = {t.get('name', ''): t.get('value', '')
                for t in menu_form.select('input[type="hidden"]')}
        data.update({
            'rx.sync.source': 'menuForm:mainMenu',
            'menuForm:mainMenu': 'menuForm:mainMenu',
            'menuForm:mainMenu_menuid': '0_3_0_0'
        })
        response = self.ses.post('https://portal.it-chiba.ac.jp/uprx/up/bs/bsa001/Bsa00101.xhtml', data)
        soup = BeautifulSoup(response.content, 'lxml')
        return soup
    
    def func_post(self, data):
        post_data = {**self.func_data, **data, **self.rx_data}
        response = self.ses.post('https://portal.it-chiba.ac.jp/uprx/up/bs/bsd007/Bsd00701.xhtml', post_data)
        soup = BeautifulSoup(response.content, 'lxml')
        self.rx_data.update({t.get('name'): t.get('value') for t in soup.select('input[name^="rx-"]')})
        return soup
    
    def post_iter(self):
        tab_panel = self.soup.select_one('.ui-tabs-panel:nth-child(2)')
        for keiji in tab_panel.select('#keiji'):
            exclamation = not keiji.select_one('i.fa-exclamation-circle.hiddenStyle')
            lightbulb = not keiji.select_one('i.fa-lightbulb-circle.hiddenStyle')
            category = keiji.select_one('span.keijiCategory').text.strip()
            title_tag = keiji.select_one('a')
            title = title_tag.text.strip()
            date = datetime.strptime(title_tag.next_sibling.strip(), '%Y/%m/%d').date()
            yield {'exclamation': exclamation, 'lightbulb': lightbulb, 'category': category, 'title': title, 'date': date}


class FullNoticeboard(Noticeboard):
    def __init__(self, small_board:Noticeboard):
        self.ses = small_board.ses
        self.small_board = small_board
        self.soup = self.load()

        self.func_form = self.small_board.soup.select_one('form#funcForm')
        self.func_data = {t.get('name'): t.get('value', '') for t in self.func_form.select('input[type="hidden"]')}
        self.rx_data = {k: v for k, v in self.func_data.items() if k.startswith('rx-')}
    
    def load(self):
        tab_id = self.small_board.soup.select_one('li[role="tab"]:nth-of-type(2) a').get('href')[1:]
        tab_move_data = {
            'javax.faces.partial.ajax': True,
            'javax.faces.source': 'funcForm:tabArea',
            'javax.faces.partial.execute': 'funcForm:tabArea',
            'javax.faces.partial.render': "funcForm:tabArea",
            'javax.faces.behavior.event': 'tabChange',
            'javax.faces.partial.event': 'tabChange',
            'funcForm:tabArea_newTab': tab_id,
            'funcForm:tabArea_tabindex': 1,
            'funcForm:tabArea_activeIndex': 1,
        }
        self.small_board.func_post(tab_move_data)
        tab_panel = self.small_board.soup.select_one('.ui-tabs-panel:nth-child(2)')
        all_show_id = tab_panel.select_one('button[title*="すべての掲示を表示"]').get('id')
        fullborard_data = {
            'javax.faces.partial.ajax': True,
            'javax.faces.source': all_show_id,
            'javax.faces.partial.execute': '@all',
            'javax.faces.partial.render': "funcForm",
            all_show_id: all_show_id,
        }
        fullboard_page = self.small_board.func_post(fullborard_data)
        return fullboard_page


def get_noticeboard_json(user_id, password, full=False):
    top_page = TopPage(user_id, password)
    board = Noticeboard(top_page)
    if full:
        board = FullNoticeboard(board)
    body = list(board.post_iter())
    return body
