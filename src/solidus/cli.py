"""Solidus 命令行。退出码只说明程序有没有跑起来，不是测试结论。"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import typer

from solidus.config import load_settings
from solidus.db import DB

app = typer.Typer(no_args_is_help=True, help="Solidus 固相线")
client_app = typer.Typer(no_args_is_help=True, help="按脚本向 Telegram 发命令")
script_app = typer.Typer(no_args_is_help=True, help="检查并接受脚本")
ledger_app = typer.Typer(no_args_is_help=True, help="导出 Telegram 记录")
app.add_typer(client_app, name="client")
app.add_typer(script_app, name="script")
app.add_typer(ledger_app, name="ledger")


def _utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8")
        except Exception:
            return


@app.callback()
def _setup() -> None:
    """人守着账本。Agent 只起草。脚本只走 Telegram。"""
    _utf8()


@app.command()
def practice() -> None:
    """启动本机练习页。"""
    from solidus.practice.serve import main

    main()


@app.command()
def server() -> None:
    """从 Telegram 收命令。"""
    settings = load_settings()
    if not settings.telegram_bot_token:
        typer.echo("还没有 TELEGRAM_BOT_TOKEN。打开 docs/配置.md 填写，不要把 token 发到聊天里。")
        raise typer.Exit(2)
    from solidus.server.telegram_in import run_bot

    run_bot(settings)


@client_app.command("login")
def client_login() -> None:
    """登录用来发命令的 Telegram 用户会话。"""
    settings = load_settings()
    from solidus.client.telegram_io import login_user

    asyncio.run(login_user(settings))


@client_app.command("run")
def client_run(
    path: Path,
    server_timeout: float = 90,
    human_timeout: float = 1800,
) -> None:
    """按已接受的 script 向同一个 Telegram 聊天发命令。"""
    settings = load_settings()
    db = DB(settings.db_path)
    target = path if path.is_absolute() else settings.root / path
    from solidus.client.runner import run_script
    from solidus.client.script import ScriptError, assert_accepted
    from solidus.client.telegram_io import TelegramTransport

    try:
        ops = assert_accepted(target, settings.root, db)
    except ScriptError as exc:
        typer.echo(str(exc))
        raise typer.Exit(2) from exc
    transport = TelegramTransport(settings)
    try:
        transport.open()
        result = run_script(
            ops,
            transport,
            server_timeout=server_timeout,
            human_timeout=human_timeout,
        )
    finally:
        transport.close()
    typer.echo(result.detail)
    raise typer.Exit(0)


@script_app.command("check")
def script_check(path: Path) -> None:
    """检查脚本。wait human 后面不能自动回复。"""
    settings = load_settings()
    target = path if path.is_absolute() else settings.root / path
    errors = _check_file(target)
    if errors:
        for item in errors:
            typer.echo(item)
        raise typer.Exit(2)
    typer.echo("脚本检查通过。这不是测试结论。")


@script_app.command("accept")
def script_accept(path: Path) -> None:
    """记下你接受了这份脚本。文件必须在 clients/scripts。"""
    settings = load_settings()
    target = path if path.is_absolute() else settings.root / path
    scripts = settings.scripts_dir.resolve()
    if target.resolve().parent != scripts:
        typer.echo("只能接受 clients/scripts 里的脚本。草稿不能直接交给客户端。")
        raise typer.Exit(2)
    errors = _check_file(target)
    if errors:
        for item in errors:
            typer.echo(item)
        raise typer.Exit(2)
    from solidus.client.script import content_hash

    text = target.read_text(encoding="utf-8")
    relative = target.resolve().relative_to(settings.root).as_posix()
    DB(settings.db_path).accept("script", relative, content_hash(text))
    typer.echo(f"已接受 {relative}。")


@ledger_app.command("export")
def ledger_export(chat: str = "") -> None:
    """导出一个聊天的记录。"""
    settings = load_settings()
    chat_id = chat or settings.telegram_chat_id
    if not chat_id:
        typer.echo("请传入 --chat，或在 .env 里填写 TELEGRAM_CHAT_ID。")
        raise typer.Exit(2)
    from solidus.ledger.export import export_chat

    path = export_chat(DB(settings.db_path), chat_id, settings.ledger_dir)
    typer.echo(path.relative_to(settings.root).as_posix())


@app.command()
def accepted() -> None:
    """列出已经由人接受的 script 和 skill。"""
    settings = load_settings()
    rows = DB(settings.db_path).list_acceptances()
    if not rows:
        typer.echo("还没有人接受过 script 或 skill。")
        return
    for row in rows:
        typer.echo(f"{row['accepted_at']}  {row['kind']}  {row['name']}")


def _check_file(path: Path) -> list[str]:
    from solidus.client.script import check_script

    if not path.is_file():
        return [f"找不到脚本：{path}"]
    return check_script(path.read_text(encoding="utf-8"))
