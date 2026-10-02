"""驱动本机练习页。只把页面上的人话读回来，不宣布测试结果。"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from html import unescape
from typing import Protocol

import httpx

from solidus.server.cards import ActionResult

EMAIL = "tester@example.com"
_DD = re.compile(r'<dd id="([^"]+)"[^>]*>(.*?)</dd>', re.S)
_H1 = re.compile(r"<h1>(.*?)</h1>", re.S)
_FLASH = re.compile(r'class="flash"[^>]*>(.*?)</p>', re.S)


class PracticeError(Exception):
    def __init__(self, saw: str) -> None:
        super().__init__(saw)
        self.saw = saw


class PracticePort(Protocol):
    def ensure(self) -> None: ...

    def reset(self) -> None: ...

    def open_register(self) -> str: ...

    def register(self, name: str, role: str) -> ActionResult: ...

    def open_login(self) -> str: ...

    def login(self) -> ActionResult: ...

    def open_form(self) -> str: ...

    def submit_form(
        self, title: str, quantity: str, city: str, rush: str, note: str
    ) -> ActionResult: ...


def _plain(fragment: str) -> str:
    text = re.sub(r"<.*?>", "", fragment, flags=re.S)
    return unescape(text).strip()


def h1(html: str) -> str:
    match = _H1.search(html)
    return _plain(match.group(1)) if match else ""


def flash(html: str) -> str:
    match = _FLASH.search(html)
    return _plain(match.group(1)) if match else ""


def dds(html: str) -> dict[str, str]:
    return {key: _plain(value) for key, value in _DD.findall(html)}


class HttpPractice:
    """用和浏览器一样的表单把练习页走一遍。"""

    def __init__(
        self,
        *,
        password: str,
        client: httpx.Client | None = None,
        base_url: str = "http://127.0.0.1:8765",
        auto_start: bool = False,
    ) -> None:
        self.password = password
        self.base_url = base_url.rstrip("/")
        self.auto_start = auto_start
        self.client = client or httpx.Client(
            base_url=self.base_url,
            follow_redirects=True,
            timeout=30,
        )
        self._proc: subprocess.Popen[bytes] | None = None

    def ensure(self) -> None:
        if self._healthy():
            return
        if not self.auto_start:
            raise PracticeError("练习页没开。")
        self._spawn()
        for _ in range(50):
            if self._healthy():
                return
            time.sleep(0.1)
        raise PracticeError(f"练习页没有在 {self.base_url} 起来。")

    def _healthy(self) -> bool:
        try:
            response = self.client.get("/health")
        except httpx.HTTPError:
            return False
        return response.status_code == 200

    def _spawn(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            return
        env = dict(os.environ)
        env["PRACTICE_BASE_URL"] = self.base_url
        if self.password:
            env["PRACTICE_PASSWORD"] = self.password
        self._proc = subprocess.Popen(
            [sys.executable, "-m", "solidus.practice.serve"],
            env=env,
        )

    def reset(self) -> None:
        response = self.client.post("/_reset")
        self.client.cookies.clear()
        if response.status_code != 200:
            raise PracticeError("练习页没有清空。")

    def open_register(self) -> str:
        self._expect(self.client.get("/register"), "注册")
        return "已打开注册页。"

    def register(self, name: str, role: str) -> ActionResult:
        response = self.client.post(
            "/register",
            data={
                "name": name,
                "email": EMAIL,
                "password": self.password,
                "role": role,
                "agree": "yes",
            },
        )
        self._guard(response.text)
        fields = dds(response.text)
        message = flash(response.text)
        if message.startswith("已提交注册") and fields.get("name") and fields.get("role"):
            saw = f"已提交注册。姓名 {fields['name']}，角色{fields['role']}。"
            return ActionResult(saw=saw, proceeded=True, data=fields)
        return ActionResult(saw=message or "注册没有提交。", proceeded=False)

    def open_login(self) -> str:
        self._expect(self.client.get("/login"), "登录")
        return "已打开登录页。"

    def login(self) -> ActionResult:
        response = self.client.post(
            "/login",
            data={"email": EMAIL, "password": self.password},
        )
        self._guard(response.text)
        message = flash(response.text)
        if message == "已登录。":
            return ActionResult(saw="已登录。", proceeded=True)
        return ActionResult(saw=message or "没有登录。", proceeded=False)

    def open_form(self) -> str:
        response = self.client.get("/form")
        self._guard(response.text)
        if h1(response.text) != "表单":
            raise PracticeError("没有打开表单。")
        message = flash(response.text)
        if message:
            raise PracticeError(message)
        return "已打开表单。"

    def submit_form(
        self, title: str, quantity: str, city: str, rush: str, note: str
    ) -> ActionResult:
        response = self.client.post(
            "/form",
            data={
                "title": title,
                "quantity": quantity,
                "city": city,
                "rush": rush,
                "note": note,
            },
        )
        self._guard(response.text)
        if h1(response.text) != "提交结果":
            message = flash(response.text) or "表单没有提交。"
            return ActionResult(saw=message, proceeded=False)
        fields = dds(response.text)
        if not fields.get("title"):
            return ActionResult(saw=flash(response.text) or "还没有提交。", proceeded=False)
        saw = (
            f"已提交。标题{fields['title']}，数量 {fields['quantity']}，"
            f"城市{fields['city']}，加急 {fields['rush']}。"
        )
        return ActionResult(saw=saw, proceeded=True, data=fields)

    def _expect(self, response: httpx.Response, heading: str) -> None:
        self._guard(response.text)
        if h1(response.text) != heading:
            raise PracticeError(f"没有打开{heading}页。")

    def _guard(self, html: str) -> None:
        if self.password and self.password in html:
            raise PracticeError("练习页的响应里出现了不该出现的内容，已中止。")
