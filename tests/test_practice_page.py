from __future__ import annotations

from starlette.testclient import TestClient

from solidus.skills.practice_page import HttpPractice, dds, flash, h1

PASSWORD = "test-secret-value"


def test_register_login_form_and_done(practice: HttpPractice) -> None:
    assert practice.open_register() == "已打开注册页。"
    registered = practice.register("tester", "测试员")
    assert registered.proceeded
    assert registered.saw == "已提交注册。姓名 tester，角色测试员。"

    assert practice.open_login() == "已打开登录页。"
    logged = practice.login()
    assert logged.proceeded
    assert logged.saw == "已登录。"

    assert practice.open_form() == "已打开表单。"
    submitted = practice.submit_form("桥", "2", "多伦多", "true", "只要名字")
    assert submitted.proceeded
    assert submitted.saw == "已提交。标题桥，数量 2，城市多伦多，加急 true。"
    assert submitted.data["note"] == "只要名字"
    assert PASSWORD not in submitted.saw


def test_failed_login_is_a_sentence(practice_app, practice: HttpPractice) -> None:
    practice.register("tester", "测试员")
    client = TestClient(practice_app, follow_redirects=True)
    response = client.post("/login", data={"email": "tester@example.com", "password": "not-the-password"})
    assert "邮箱或密码不对。" in response.text
    assert h1(response.text) == "登录"
    assert PASSWORD not in response.text


def test_page_lists_roles_and_cities(practice: HttpPractice) -> None:
    register = practice.client.get("/register")
    assert "测试员" in register.text and "观察者" in register.text
    practice.register("tester", "测试员")
    practice.login()
    form = practice.client.get("/form")
    assert "多伦多" in form.text and "蒙特利尔" in form.text
    assert flash(form.text) == ""
    assert h1(form.text) == "表单"


def test_done_before_submit(practice: HttpPractice) -> None:
    page = practice.client.get("/done")
    assert "还没有提交。" in page.text
    assert dds(page.text) == {}
