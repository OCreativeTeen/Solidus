"""本机练习页。不接真实用户库，也不宣布测试结果。"""

from __future__ import annotations

import hmac
import os
import secrets
import threading
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

ROLES = ("测试员", "开发", "观察者")
CITIES = ("多伦多", "渥太华", "蒙特利尔")
EMAIL = "tester@example.com"
COOKIE = "practice_session"

app = FastAPI(title="Solidus 练习页")
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))


@dataclass
class User:
    name: str
    email: str
    role: str


@dataclass
class Sesh:
    user_email: str | None = None
    submission: dict[str, str] | None = None


@dataclass
class Store:
    lock: threading.Lock = field(default_factory=threading.Lock)
    users: dict[str, User] = field(default_factory=dict)
    sessions: dict[str, Sesh] = field(default_factory=dict)


store = Store()


def _password() -> str:
    return os.environ.get("PRACTICE_PASSWORD", "")


def _sid(request: Request) -> str | None:
    return request.cookies.get(COOKIE)


def _sesh(request: Request) -> Sesh | None:
    sid = _sid(request)
    if not sid:
        return None
    with store.lock:
        return store.sessions.get(sid)


def _render(request: Request, name: str, context: dict):
    try:
        return templates.TemplateResponse(request, name, context)
    except TypeError:
        payload = {"request": request, **context}
        return templates.TemplateResponse(name, payload)


@app.get("/health")
def health() -> JSONResponse:
    return JSONResponse({"ok": True})


@app.post("/_reset")
def reset() -> JSONResponse:
    with store.lock:
        store.users.clear()
        store.sessions.clear()
    return JSONResponse({"ok": True})


@app.get("/")
def root() -> RedirectResponse:
    return RedirectResponse("/register")


@app.get("/register")
def register_form(request: Request):
    return _render(
        request,
        "register.html",
        {
            "title": "注册",
            "flash": "",
            "done": False,
            "name": "",
            "email": EMAIL,
            "role": "",
            "roles": ROLES,
        },
    )


@app.post("/register")
def register_submit(
    request: Request,
    name: str = Form(""),
    email: str = Form(""),
    password: str = Form(""),
    role: str = Form(""),
    agree: str = Form(""),
):
    problems: list[str] = []
    if not name.strip():
        problems.append("请填写姓名。")
    if not email.strip():
        problems.append("请填写邮箱。")
    if not password:
        problems.append("请填写密码。")
    if role not in ROLES:
        problems.append("请选择角色。")
    if agree != "yes":
        problems.append("请先同意条款。")
    expected = _password()
    if not problems and len(expected) < 8:
        problems.append("本机还没有可用的练习密码。")
    if not problems and not hmac.compare_digest(password, expected):
        problems.append("密码和本机练习密码不一致。")
    if problems:
        return _render(
            request,
            "register.html",
            {
                "title": "注册",
                "flash": "".join(problems),
                "done": False,
                "name": name.strip(),
                "email": email.strip() or EMAIL,
                "role": role,
                "roles": ROLES,
            },
        )
    with store.lock:
        store.users[email.strip()] = User(name=name.strip(), email=email.strip(), role=role)
    return _render(
        request,
        "register.html",
        {
            "title": "注册",
            "flash": "已提交注册。",
            "done": True,
            "name": name.strip(),
            "email": email.strip(),
            "role": role,
            "roles": ROLES,
        },
    )


@app.get("/login")
def login_form(request: Request):
    return _render(
        request,
        "login.html",
        {"title": "登录", "flash": "", "logged_in": False},
    )


@app.post("/login")
def login_submit(
    request: Request,
    email: str = Form(""),
    password: str = Form(""),
):
    expected = _password()
    with store.lock:
        user = store.users.get(email.strip())
    if len(expected) < 8:
        flash = "本机还没有可用的练习密码。"
        ok = False
    elif user is None or not hmac.compare_digest(password, expected):
        flash = "邮箱或密码不对。"
        ok = False
    else:
        flash = "已登录。"
        ok = True
    response = _render(
        request,
        "login.html",
        {"title": "登录", "flash": flash, "logged_in": ok},
    )
    if ok:
        sid = secrets.token_urlsafe(24)
        with store.lock:
            store.sessions[sid] = Sesh(user_email=user.email)
        response.set_cookie(COOKIE, sid, httponly=True, samesite="lax")
    return response


def _require_user(request: Request) -> Sesh | None:
    sesh = _sesh(request)
    if sesh is None or not sesh.user_email:
        return None
    return sesh


@app.get("/form")
def form_page(request: Request):
    if _require_user(request) is None:
        return _render(
            request,
            "form.html",
            {
                "title": "表单",
                "flash": "请先登录。",
                "field_title": "",
                "quantity": "",
                "city": "",
                "rush": "",
                "note": "",
                "cities": CITIES,
            },
        )
    return _render(
        request,
        "form.html",
        {
            "title": "表单",
            "flash": "",
            "field_title": "",
            "quantity": "",
            "city": "",
            "rush": "",
            "note": "",
            "cities": CITIES,
        },
    )


@app.post("/form")
def form_submit(
    request: Request,
    title: str = Form(""),
    quantity: str = Form(""),
    city: str = Form(""),
    rush: str = Form(""),
    note: str = Form(""),
):
    sesh = _require_user(request)
    values = {
        "title": "表单",
        "flash": "",
        "field_title": title,
        "quantity": quantity,
        "city": city,
        "rush": rush,
        "note": note,
        "cities": CITIES,
    }
    if sesh is None:
        values["flash"] = "请先登录。"
        return _render(request, "form.html", values)
    problems: list[str] = []
    if not title.strip():
        problems.append("请填写标题。")
    if not quantity.strip().isdigit():
        problems.append("数量要是数字。")
    if city not in CITIES:
        problems.append("请选择城市。")
    if rush not in {"true", "false"}:
        problems.append("请选择是否加急。")
    if problems:
        values["flash"] = "".join(problems)
        return _render(request, "form.html", values)
    submission = {
        "title": title.strip(),
        "quantity": str(int(quantity)),
        "city": city,
        "rush": rush,
        "note": note.strip(),
    }
    with store.lock:
        current = store.sessions.get(_sid(request) or "")
        if current is not None:
            current.submission = submission
    return RedirectResponse("/done", status_code=303)


@app.get("/done")
def done(request: Request):
    sesh = _sesh(request)
    submission = sesh.submission if sesh else None
    flash = "" if submission else "还没有提交。"
    return _render(
        request,
        "done.html",
        {"title": "提交结果", "flash": flash, "submission": submission},
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8765)
