#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import requests
from bs4 import BeautifulSoup


class LoginError(Exception):
    pass


HEADERS = {
    "Content-Type": "application/x-www-form-urlencoded",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/69.0.3497.100",
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
            "loginForm:loginButton": "",
        }
        url = "https://portal.it-chiba.ac.jp/uprx/up/pk/pky001/Pky00101.xhtml"
        response = self.ses.post(url, login_form)
        soup = BeautifulSoup(response.content, "xml")
        if not soup.select_one("form#menuForm"):
            raise LoginError("ログイン失敗")
        return soup
