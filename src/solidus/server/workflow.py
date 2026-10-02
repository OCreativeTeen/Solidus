"""固定 workflow。出站只有卡片和短确认，不打分。"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from solidus.agent.companion import Companion, ConfigError
from solidus.config import MIN_PASSWORD_LEN, Settings
from solidus.db import DB, Session
from solidus.ledger.export import export_chat
from solidus.redact import redact
from solidus.server.cards import Card
from solidus.server.commands import Command, parse_command
from solidus.skills.gemini_prompt import GeminiPrompt, GeminiResult
from solidus.skills.loader import DraftError, LoaderError, SkillLoader
from solidus.skills.practice_page import PracticeError, PracticePort

logger = logging.getLogger(__name__)

HELP = (
    "命令：/run practice、注册 姓名 角色、登录、"
    "填表 标题 数量 城市 true或false 备注、打开 gemini、/export、/skills、/help。"
    "卡片只回复 1、2 或 3。"
)

BUILTIN_SKILLS = "practice_page、chrome_debug、gemini_prompt"


@dataclass
class Out:
    text: str
    kind: str
    human_required: bool = False
    step: str = ""


class Workflow:
    def __init__(
        self,
        settings: Settings,
        db: DB,
        practice: PracticePort,
        gemini: GeminiPrompt,
        agent: Companion,
        loader: SkillLoader | None = None,
    ) -> None:
        self.settings = settings
        self.db = db
        self.practice = practice
        self.gemini = gemini
        self.agent = agent
        self.loader = loader or SkillLoader(settings.promoted_dir, settings.drafts_dir)

    def handle(self, chat_id: str, text: str) -> list[str]:
        """只看聊天里的文本。不看发送者是不是客户端。"""
        cleaned, leaked = redact(text, self.settings.secrets)
        session = self.db.load(chat_id)
        if leaked:
            self.db.add_message(
                chat_id=chat_id,
                sender="human",
                text="[已省略]",
                phase=session.phase,
                kind="command",
            )
            outs = [
                Out(
                    "请不要在聊天里发送密钥。密码和 token 只放在本机 .env。",
                    "ack",
                )
            ]
            return self._commit(session, outs)
        kind = _inbound_kind(session, cleaned)
        self.db.add_message(
            chat_id=chat_id,
            sender="human",
            text=cleaned,
            phase=session.phase,
            kind=kind,
            human_required=bool(session.pending and session.pending.get("human_required") and kind == "decision"),
        )
        try:
            outs = self._turn(session, cleaned)
        except Exception:
            logger.exception("workflow step failed phase=%s", session.phase)
            session.pending = None
            session.phase = "stopped"
            outs = [Out("这一步没有做完。请看服务器控制台。聊天先交给你。", "ack")]
        return self._commit(session, outs)

    def _commit(self, session: Session, outs: list[Out]) -> list[str]:
        self.db.save(session)
        shown: list[str] = []
        for item in outs:
            text, _leaked = redact(item.text, self.settings.secrets)
            self.db.add_message(
                chat_id=session.chat_id,
                sender="server",
                text=text,
                phase=session.phase,
                kind=item.kind,
                human_required=item.human_required,
                step=item.step,
            )
            shown.append(text)
        return shown

    def _turn(self, session: Session, text: str) -> list[Out]:
        command = parse_command(text)
        if command.kind in {"help", "skills", "export"}:
            extra = self._meta(session, command)
            if session.pending:
                return extra + [self._rerender(session)]
            return extra
        if command.kind == "run" and command.args.get("name") == "practice":
            return self._start_practice(session)
        if command.kind == "run" and not command.args.get("name"):
            return [Out("用法：/run practice", "ack")]
        if session.pending:
            if command.kind == "choice":
                return self._apply(session, command.args["value"])
            return [self._rerender(session)]
        if command.kind == "choice":
            return [Out("现在没有待选的卡片。", "ack")]
        if command.kind == "register":
            return self._do_register(session, command.args["name"], command.args["role"], from_command=True)
        if command.kind == "register_bad":
            return [Out("注册要写成：注册 姓名 角色。例如：注册 tester 测试员", "ack")]
        if command.kind == "login":
            return self._do_login(session, from_command=True)
        if command.kind == "login_bad":
            return [Out("登录不带参数。请只发送：登录", "ack")]
        if command.kind == "form":
            return self._do_form(session, command.args, from_command=True)
        if command.kind == "form_bad":
            return [
                Out(
                    "填表要写成：填表 标题 数量 城市 true或false 备注。例如：填表 桥 2 多伦多 true 只要名字",
                    "ack",
                )
            ]
        if command.kind == "gemini":
            return self._gemini_command(session)
        if command.kind == "run":
            return self._ask_draft(session, text)
        return self._unknown(session, text)

    def _meta(self, session: Session, command: Command) -> list[Out]:
        if command.kind == "help":
            return [Out(HELP, "ack")]
        if command.kind == "skills":
            return [Out(self._skill_lines(), "ack")]
        path = export_chat(self.db, session.chat_id, self.settings.ledger_dir)
        relative = path.relative_to(self.settings.root).as_posix()
        return [Out(f"已导出 {relative}。", "ack")]

    def _skill_lines(self) -> str:
        promoted = [item.name for item in self.loader.load()]
        drafts = sorted(path.name for path in self.settings.drafts_dir.glob("*.py"))
        promoted_text = "、".join(promoted) if promoted else "无"
        draft_text = "、".join(drafts) if drafts else "无"
        return f"内置：{BUILTIN_SKILLS}\n已晋升：{promoted_text}\n草稿：{draft_text}"

    def _start_practice(self, session: Session) -> list[Out]:
        session.bag = {}
        session.pending = None
        try:
            self.practice.ensure()
            self.practice.reset()
        except PracticeError as exc:
            return self._ask(
                session,
                Card(
                    step="练习页还没就绪",
                    saw=exc.saw,
                    question="接下来怎么办",
                    options=("重试", "先不做", "停下"),
                    human_required=True,
                ),
                {
                    "1": {"op": "start_practice"},
                    "2": {"op": "ack", "text": "先不做练习页。", "phase": "idle"},
                    "3": {"op": "stop"},
                },
                phase="decide_practice",
            )
        return self._ask(
            session,
            Card(
                step="练习页已就绪",
                saw=f"本机页面可以打开。地址是 {self.settings.practice_base_url}",
                question="从哪一步开始",
                options=("从注册开始", "从登录开始", "停下"),
            ),
            {
                "1": {"op": "open_register"},
                "2": {"op": "open_login"},
                "3": {"op": "stop"},
            },
            phase="choose_entry",
        )

    def _do_register(self, session: Session, name: str, role: str, *, from_command: bool) -> list[Out]:
        if from_command and session.phase != "await_register":
            return [Out(_hint(session.phase), "ack")]
        if not self.settings.password_ready:
            return self._ask_password(session, {"op": "register", "name": name, "role": role})
        try:
            result = self.practice.register(name, role)
        except PracticeError as exc:
            return self._trouble(session, "注册没有走完", exc.saw, {"op": "register", "name": name, "role": role})
        if not result.proceeded:
            return self._trouble(session, "注册没有提交", result.saw, {"op": "register", "name": name, "role": role})
        session.bag["name"] = name
        session.bag["role"] = role
        return self._ask(
            session,
            Card(
                step="注册已提交",
                saw=result.saw,
                question="下一步做什么",
                options=("去登录", "重做注册", "停下"),
            ),
            {
                "1": {"op": "open_login"},
                "2": {"op": "open_register"},
                "3": {"op": "stop"},
            },
            phase="decide_after_register",
        )

    def _do_login(self, session: Session, *, from_command: bool) -> list[Out]:
        if from_command and session.phase != "await_login":
            return [Out(_hint(session.phase), "ack")]
        if not self.settings.password_ready:
            return self._ask_password(session, {"op": "login"})
        try:
            result = self.practice.login()
        except PracticeError as exc:
            return self._trouble(session, "登录没有走完", exc.saw, {"op": "login"})
        if not result.proceeded:
            return self._trouble(session, "没有登录", result.saw, {"op": "login"})
        return self._ask(
            session,
            Card(
                step="已登录",
                saw=result.saw,
                question="下一步做什么",
                options=("去填表", "停在登录后", "停下"),
            ),
            {
                "1": {"op": "open_form"},
                "2": {"op": "stop_after_login"},
                "3": {"op": "stop"},
            },
            phase="decide_after_login",
        )

    def _do_form(self, session: Session, args: dict[str, Any], *, from_command: bool) -> list[Out]:
        if from_command and session.phase != "await_form":
            return [Out(_hint(session.phase), "ack")]
        try:
            result = self.practice.submit_form(
                args["title"], args["quantity"], args["city"], args["rush"], args["note"]
            )
        except PracticeError as exc:
            return self._trouble(session, "表单没有走完", exc.saw, {"op": "form", **args})
        if not result.proceeded:
            return self._trouble(session, "表单没有提交", result.saw, {"op": "form", **args})
        session.bag["form"] = result.data
        return self._ask(
            session,
            Card(
                step="表单已提交",
                saw=result.saw,
                question="这次提交可以吗",
                options=("可以", "不行，重做", "停下"),
                human_required=True,
            ),
            {
                "1": {"op": "ask_gemini"},
                "2": {"op": "open_form"},
                "3": {"op": "stop"},
            },
            phase="decide_form",
        )

    def _gemini_command(self, session: Session) -> list[Out]:
        if session.phase not in {"idle", "done", "stopped"}:
            return [Out("先把当前这一步走完。现在还不能打开 Gemini。", "ack")]
        return self._ask_gemini(session)

    def _ask_gemini(self, session: Session) -> list[Out]:
        return self._ask(
            session,
            Card(
                step="准备打开 Gemini",
                saw="下一步要接上已打开的调试 Chrome，并打开 Gemini。",
                question="允许接上这个 Chrome 吗",
                options=("允许", "跳过", "停下"),
                human_required=True,
            ),
            {
                "1": {"op": "run_gemini"},
                "2": {"op": "skip_gemini"},
                "3": {"op": "stop"},
            },
            phase="decide_gemini",
        )

    def _ask_password(self, session: Session, retry: dict[str, Any]) -> list[Out]:
        return self._ask(
            session,
            Card(
                step="练习密码还不能用",
                saw=(
                    "本机的 PRACTICE_PASSWORD 还不能用。"
                    f"请在 .env 里设成至少 {MIN_PASSWORD_LEN} 位，不要发到聊天里。"
                ),
                question="接下来怎么办",
                options=("我已改好，重试", "先不做", "停下"),
                human_required=True,
            ),
            {
                "1": {"op": "reload_password", "retry": retry},
                "2": {"op": "ack", "text": "先不做这一步。", "phase": session.phase},
                "3": {"op": "stop"},
            },
            phase="decide_password",
        )

    def _trouble(self, session: Session, step: str, saw: str, retry: dict[str, Any]) -> list[Out]:
        return self._ask(
            session,
            Card(
                step=step,
                saw=saw,
                question="接下来怎么办",
                options=("重试", "先不做", "停下"),
                human_required=True,
            ),
            {
                "1": retry,
                "2": {"op": "ack", "text": "先不做这一步。", "phase": "idle"},
                "3": {"op": "stop"},
            },
            phase="decide_trouble",
        )

    def _unknown(self, session: Session, text: str) -> list[Out]:
        if session.phase in {"idle", "done", "stopped"}:
            return self._ask_draft(session, text)
        return [Out(_hint(session.phase), "ack")]

    def _ask_draft(self, session: Session, command: str) -> list[Out]:
        skill = self.loader.match(command)
        if skill is not None:
            return self._run_dynamic(session, skill, command)
        return self._ask(
            session,
            Card(
                step="没有对应的 skill",
                saw=f"这句话还没有已晋升的 skill：{_clip(command)}",
                question="要起草一份 skill 吗",
                options=("起草", "不用", "停下"),
                human_required=True,
            ),
            {
                "1": {"op": "draft", "command": command},
                "2": {"op": "ack", "text": "好，不起草。", "phase": "idle"},
                "3": {"op": "stop"},
            },
            phase="decide_draft",
        )

    def _run_dynamic(self, session: Session, skill: Any, command: str) -> list[Out]:
        try:
            result = skill.run(
                command,
                {"ledger": str(self.settings.ledger_dir), "root": str(self.settings.root)},
            )
            saw = str(result.get("saw") or "这一步做完了，请你看。")
        except Exception:
            logger.exception("skill failed name=%s", getattr(skill, "name", ""))
            saw = "这个 skill 没有做完。"
        return self._ask(
            session,
            Card(
                step=f"skill {skill.name}",
                saw=saw,
                question="这一步可以吗",
                options=("可以", "不行，重做", "停下"),
                human_required=True,
            ),
            {
                "1": {"op": "ack", "text": "已记下你的选择：可以。", "phase": "done"},
                "2": {"op": "rerun_skill", "command": command},
                "3": {"op": "stop"},
            },
            phase="decide_skill",
        )

    def _apply(self, session: Session, choice: str) -> list[Out]:
        pending = session.pending or {}
        spec = pending.get("choices", {}).get(choice)
        session.pending = None
        if not isinstance(spec, dict):
            return [Out("这个选项没有对应的下一步。聊天交给你。", "ack")]
        return self._exec(session, spec)

    def _exec(self, session: Session, spec: dict[str, Any]) -> list[Out]:
        op = str(spec.get("op", ""))
        method = getattr(self, f"_op_{op}", None)
        if method is None:
            return [Out("这一步没有对应的动作。聊天交给你。", "ack")]
        return method(session, spec)

    def _ask(self, session: Session, card: Card, choices: dict[str, Any], phase: str) -> list[Out]:
        rendered = card.render()
        session.phase = phase
        session.pending = {
            "text": rendered,
            "human_required": card.human_required,
            "step": card.step,
            "choices": choices,
        }
        return [Out(rendered, "card", card.human_required, card.step)]

    def _ack(self, session: Session, text: str, phase: str | None = None) -> list[Out]:
        if phase is not None:
            session.phase = phase
        session.pending = None
        return [Out(text, "ack")]

    def _rerender(self, session: Session) -> Out:
        pending = session.pending or {}
        text = "请只回复 1、2 或 3。\n" + str(pending.get("text", ""))
        return Out(text, "card", bool(pending.get("human_required")), str(pending.get("step", "")))

    def _op_start_practice(self, session: Session, spec: dict[str, Any]) -> list[Out]:
        del spec
        return self._start_practice(session)

    def _op_open_register(self, session: Session, spec: dict[str, Any]) -> list[Out]:
        del spec
        try:
            saw = self.practice.open_register()
        except PracticeError as exc:
            return self._trouble(session, "没有打开注册页", exc.saw, {"op": "open_register"})
        session.phase = "await_register"
        session.pending = None
        return [Out(saw, "ack")]

    def _op_open_login(self, session: Session, spec: dict[str, Any]) -> list[Out]:
        del spec
        try:
            saw = self.practice.open_login()
        except PracticeError as exc:
            return self._trouble(session, "没有打开登录页", exc.saw, {"op": "open_login"})
        session.phase = "await_login"
        session.pending = None
        return [Out(saw, "ack")]

    def _op_open_form(self, session: Session, spec: dict[str, Any]) -> list[Out]:
        del spec
        try:
            saw = self.practice.open_form()
        except PracticeError as exc:
            return self._trouble(session, "没有打开表单", exc.saw, {"op": "open_form"})
        session.phase = "await_form"
        session.pending = None
        return [Out(saw, "ack")]

    def _op_stop(self, session: Session, spec: dict[str, Any]) -> list[Out]:
        del spec
        return self._ack(session, "已停下。聊天交给你。", "stopped")

    def _op_stop_after_login(self, session: Session, spec: dict[str, Any]) -> list[Out]:
        del spec
        return self._ack(session, "停在登录后。聊天交给你。", "stopped")

    def _op_skip_gemini(self, session: Session, spec: dict[str, Any]) -> list[Out]:
        del spec
        return self._ack(session, "已跳过 Gemini。聊天交给你。", "stopped")

    def _op_ack(self, session: Session, spec: dict[str, Any]) -> list[Out]:
        return self._ack(session, str(spec.get("text", "好。")), spec.get("phase"))

    def _op_register(self, session: Session, spec: dict[str, Any]) -> list[Out]:
        return self._do_register(session, str(spec["name"]), str(spec["role"]), from_command=False)

    def _op_login(self, session: Session, spec: dict[str, Any]) -> list[Out]:
        del spec
        return self._do_login(session, from_command=False)

    def _op_form(self, session: Session, spec: dict[str, Any]) -> list[Out]:
        return self._do_form(session, spec, from_command=False)

    def _op_ask_gemini(self, session: Session, spec: dict[str, Any]) -> list[Out]:
        del spec
        return self._ask_gemini(session)

    def _op_run_gemini(self, session: Session, spec: dict[str, Any]) -> list[Out]:
        del spec
        result = self.gemini.run()
        return self._after_gemini(session, result)

    def _after_gemini(self, session: Session, result: GeminiResult) -> list[Out]:
        session.bag["gemini_status"] = result.status
        if result.status == "saved":
            return self._ask(
                session,
                Card(
                    step="街道 JSON 已写入",
                    saw=result.saw,
                    question="这份 JSON 可以用吗",
                    options=("这份可以用", "不行，重做", "停下"),
                    human_required=True,
                ),
                {
                    "1": {"op": "accept_json", "label": "这份可以用"},
                    "2": {"op": "run_gemini"},
                    "3": {"op": "stop"},
                },
                phase="decide_json",
            )
        if result.status == "need_login":
            question = "登录好了吗"
            options = ("我已登录，继续", "跳过这段", "停下")
        elif result.status == "no_browser":
            question = "调试 Chrome 准备好了吗"
            options = ("我已打开，重试", "跳过这段", "停下")
        elif result.status == "no_json":
            question = "没拿到数组，怎么办"
            options = ("再试一次", "跳过这段", "停下")
        else:
            question = "接下来怎么办"
            options = ("再试一次", "跳过这段", "停下")
        return self._ask(
            session,
            Card(
                step="Gemini 这一步还没写完",
                saw=result.saw,
                question=question,
                options=options,
                human_required=True,
            ),
            {
                "1": {"op": "run_gemini"},
                "2": {"op": "skip_gemini"},
                "3": {"op": "stop"},
            },
            phase="decide_gemini_block",
        )

    def _op_accept_json(self, session: Session, spec: dict[str, Any]) -> list[Out]:
        label = str(spec.get("label", "这份可以用"))
        return self._ack(session, f"已记下你的选择：{label}。", "done")

    def _op_reload_password(self, session: Session, spec: dict[str, Any]) -> list[Out]:
        from solidus.config import load_settings

        fresh = load_settings()
        self.settings.practice_password = fresh.practice_password
        retry = spec.get("retry")
        if not isinstance(retry, dict):
            return self._ack(session, "没有可重试的步骤。", "idle")
        return self._exec(session, retry)

    def _op_draft(self, session: Session, spec: dict[str, Any]) -> list[Out]:
        command = str(spec.get("command", ""))
        try:
            drafted = self.agent.draft(command)
        except ConfigError:
            return self._ask_model_config(session, command)
        except DraftError as exc:
            return self._ask_draft_failed(session, command, exc)
        return self._ask_promote(session, drafted.path.name, drafted.summary, command)

    def _op_rewrite(self, session: Session, spec: dict[str, Any]) -> list[Out]:
        command = str(session.bag.get("draft_command") or spec.get("command") or "")
        raw_path = str(session.bag.get("draft_path", ""))
        from pathlib import Path

        path = Path(raw_path) if raw_path else self.settings.drafts_dir / "missing.py"
        try:
            drafted = self.agent.rewrite(path, command)
        except ConfigError:
            return self._ask_model_config(session, command)
        except DraftError as exc:
            return self._ask_draft_failed(session, command, exc)
        return self._ask_promote(session, drafted.path.name, drafted.summary, command)

    def _ask_model_config(self, session: Session, command: str) -> list[Out]:
        return self._ask(
            session,
            Card(
                step="模型接口还没配好",
                saw="还没配置模型接口，草稿写不出来。请在本机 .env 填写 OPENAI_API_KEY，不要发到聊天里。",
                question="接下来怎么办",
                options=("我已写好配置，再试", "不用起草", "停下"),
                human_required=True,
            ),
            {
                "1": {"op": "reload_model", "command": command},
                "2": {"op": "ack", "text": "好，不起草。", "phase": "idle"},
                "3": {"op": "stop"},
            },
            phase="decide_model",
        )

    def _ask_draft_failed(self, session: Session, command: str, exc: DraftError) -> list[Out]:
        return self._ask(
            session,
            Card(
                step="草稿没法用",
                saw=str(exc),
                question="接下来怎么办",
                options=("退回重写", "不用", "停下"),
                human_required=True,
            ),
            {
                "1": {"op": "draft", "command": command},
                "2": {"op": "ack", "text": "好，不起草。", "phase": "idle"},
                "3": {"op": "stop"},
            },
            phase="decide_draft_failed",
        )

    def _ask_promote(self, session: Session, filename: str, summary: str, command: str) -> list[Out]:
        path = self.settings.drafts_dir / filename
        session.bag["draft_path"] = str(path)
        session.bag["draft_command"] = command
        session.bag["draft_summary"] = summary
        return self._ask(
            session,
            Card(
                step="草稿已写好",
                saw=(
                    f"草稿在 skills/drafts/{filename}。摘要：{_clip(summary) or '无'}。"
                    "请先打开文件再选。起草的代码现在不会执行。"
                ),
                question="这份草稿怎么处理",
                options=("晋升", "退回重写", "先放着"),
                human_required=True,
            ),
            {
                "1": {"op": "promote"},
                "2": {"op": "rewrite", "command": command},
                "3": {"op": "hold"},
            },
            phase="decide_promote",
        )

    def _op_reload_model(self, session: Session, spec: dict[str, Any]) -> list[Out]:
        from solidus.config import load_settings

        fresh = load_settings()
        model = self.agent.model
        if hasattr(model, "api_key"):
            model.api_key = fresh.openai_api_key
            model.base_url = fresh.openai_base_url
            model.model = fresh.openai_model
        self.settings.openai_api_key = fresh.openai_api_key
        self.settings.openai_base_url = fresh.openai_base_url
        self.settings.openai_model = fresh.openai_model
        self.agent.secrets = self.settings.secrets
        return self._op_draft(session, spec)

    def _op_promote(self, session: Session, spec: dict[str, Any]) -> list[Out]:
        del spec
        from pathlib import Path

        raw = str(session.bag.get("draft_path", ""))
        if not raw:
            return self._ack(session, "没有可晋升的草稿。", "idle")
        path = Path(raw)
        try:
            dest = self.loader.promote(path, self.settings.secrets)
        except (DraftError, LoaderError) as exc:
            return self._ack(session, str(exc), "idle")
        except Exception:
            logger.exception("promote failed")
            return self._ack(session, "晋升没有做成。", "idle")
        digest = _hash_text(dest.read_text(encoding="utf-8"))
        self.db.accept("skill", dest.name, digest)
        session.phase = "idle"
        session.pending = None
        return [
            Out(f"已晋升到 skills/promoted/{dest.name}。这份 skill 已由你接受。", "ack")
        ]

    def _op_hold(self, session: Session, spec: dict[str, Any]) -> list[Out]:
        del spec
        return self._ack(session, "草稿先放着。还在 skills/drafts，没有晋升。", "idle")

    def _op_rerun_skill(self, session: Session, spec: dict[str, Any]) -> list[Out]:
        command = str(spec.get("command", ""))
        skill = self.loader.match(command)
        if skill is None:
            return self._ack(session, "没有找到已晋升的 skill。", "idle")
        return self._run_dynamic(session, skill, command)


def _inbound_kind(session: Session, text: str) -> str:
    command = parse_command(text)
    if command.kind != "choice":
        return "command"
    if session.pending and session.pending.get("human_required"):
        return "decision"
    return "choice"


def _hint(phase: str) -> str:
    hints = {
        "idle": "先发送 /run practice。想起草 skill 也可以直接说。",
        "await_register": "请发送注册。例如：注册 tester 测试员",
        "await_login": "请发送：登录",
        "await_form": "请发送填表。例如：填表 桥 2 多伦多 true 只要名字",
        "done": "这一轮已经记下你的选择。可以 /export，或再发 /run practice。",
        "stopped": "已经停下。可以 /export，或再发 /run practice。",
    }
    return hints.get(phase, "这一步还在等命令。发送 /help 可以看命令。")


def _clip(text: str, limit: int = 80) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1] + "…"


def _hash_text(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.replace("\r\n", "\n").encode("utf-8")).hexdigest()
