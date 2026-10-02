"""用 Playwright 打开练习页。Gemini 那段不走这里，那边只连接已打开的 Chrome。"""

from __future__ import annotations

from solidus.server.cards import ActionResult
from solidus.skills.practice_page import EMAIL, HttpPractice, PracticeError


class PlaywrightPractice:
    def __init__(self, *, password: str, base_url: str, auto_start: bool = True) -> None:
        self.password = password
        self.base_url = base_url.rstrip("/")
        self._http = HttpPractice(password=password, base_url=base_url, auto_start=auto_start)
        self._playwright = None
        self._browser = None
        self._page = None

    def ensure(self) -> None:
        self._http.ensure()
        if self._page is not None:
            return
        from playwright.sync_api import sync_playwright

        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=True)
        self._page = self._browser.new_page()

    def reset(self) -> None:
        self._http.reset()
        if self._page is not None:
            self._page.context.clear_cookies()

    def open_register(self) -> str:
        self._goto("/register", "注册")
        return "已打开注册页。"

    def register(self, name: str, role: str) -> ActionResult:
        self.open_register()
        page = self._page
        assert page is not None
        page.fill("#name", name)
        page.fill("#email", EMAIL)
        page.fill("#password", self.password)
        page.select_option("#role", label=role)
        page.check("#agree")
        page.click("button[type=submit]")
        message = page.locator(".flash").inner_text().strip()
        if message.startswith("已提交注册"):
            seen_name = page.locator("#name").inner_text().strip()
            seen_role = page.locator("#role").inner_text().strip()
            saw = f"已提交注册。姓名 {seen_name}，角色{seen_role}。"
            return ActionResult(saw=saw, proceeded=True)
        return ActionResult(saw=message or "注册没有提交。", proceeded=False)

    def open_login(self) -> str:
        self._goto("/login", "登录")
        return "已打开登录页。"

    def login(self) -> ActionResult:
        self.open_login()
        page = self._page
        assert page is not None
        page.fill("#email", EMAIL)
        page.fill("#password", self.password)
        page.click("button[type=submit]")
        message = page.locator(".flash").inner_text().strip()
        if message == "已登录。":
            return ActionResult(saw="已登录。", proceeded=True)
        return ActionResult(saw=message or "没有登录。", proceeded=False)

    def open_form(self) -> str:
        page = self._require()
        page.goto(self.base_url + "/form")
        if page.locator("h1").inner_text().strip() != "表单":
            raise PracticeError("没有打开表单。")
        if page.locator(".flash").count():
            message = page.locator(".flash").inner_text().strip()
            if message:
                raise PracticeError(message)
        return "已打开表单。"

    def submit_form(
        self, title: str, quantity: str, city: str, rush: str, note: str
    ) -> ActionResult:
        self.open_form()
        page = self._require()
        page.fill("#title", title)
        page.fill("#quantity", quantity)
        page.select_option("#city", label=city)
        page.check("#rush-true" if rush == "true" else "#rush-false")
        page.fill("#note", note)
        page.click("button[type=submit]")
        if page.locator("h1").inner_text().strip() != "提交结果":
            message = ""
            if page.locator(".flash").count():
                message = page.locator(".flash").inner_text().strip()
            return ActionResult(saw=message or "表单没有提交。", proceeded=False)
        fields = {
            "title": page.locator("#title").inner_text().strip(),
            "quantity": page.locator("#quantity").inner_text().strip(),
            "city": page.locator("#city").inner_text().strip(),
            "rush": page.locator("#rush").inner_text().strip(),
        }
        saw = (
            f"已提交。标题{fields['title']}，数量 {fields['quantity']}，"
            f"城市{fields['city']}，加急 {fields['rush']}。"
        )
        return ActionResult(saw=saw, proceeded=True, data=fields)

    def close(self) -> None:
        if self._browser is not None:
            self._browser.close()
        if self._playwright is not None:
            self._playwright.stop()
        self._page = None
        self._browser = None
        self._playwright = None

    def _goto(self, path: str, heading: str) -> None:
        page = self._require()
        page.goto(self.base_url + path)
        if page.locator("h1").inner_text().strip() != heading:
            raise PracticeError(f"没有打开{heading}页。")

    def _require(self):
        self.ensure()
        if self._page is None:
            raise PracticeError("练习页浏览器没有起来。")
        return self._page
