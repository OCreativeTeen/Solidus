"""客户端只向同一个聊天发文本。"""

from __future__ import annotations

from dataclasses import dataclass

from solidus.client.script import Op
from solidus.server.cards import is_human_gate


@dataclass(frozen=True)
class ServerBatch:
    messages: tuple[str, ...]
    last_id: int

    @property
    def text(self) -> str:
        return "\n".join(self.messages)


@dataclass
class RunResult:
    status: str
    detail: str


class ChatTransport:
    """测试和 Telegram 实现同一组方法。"""

    def send(self, text: str) -> int:
        raise NotImplementedError

    def wait_server(self, after_id: int, timeout: float) -> ServerBatch | None:
        raise NotImplementedError

    def wait_human_choice(self, after_id: int, timeout: float) -> tuple[str, int] | None:
        raise NotImplementedError


def run_script(
    ops: list[Op],
    transport: ChatTransport,
    *,
    server_timeout: float = 90,
    human_timeout: float = 1800,
    echo=print,
) -> RunResult:
    last_server = ""
    last_id = 0
    index = 0
    while index < len(ops):
        op = ops[index]
        if op.kind == "send":
            if is_human_gate(last_server):
                return RunResult(
                    "handed_back",
                    "退回：这一步须由人决定，脚本却要继续发送。聊天交还人。脚本没有改。",
                )
            echo(f"发送：{op.text}")
            mid = transport.send(op.text)
            batch = transport.wait_server(mid, server_timeout)
            if batch is None or not batch.messages:
                return RunResult(
                    "handed_back",
                    "退回：没有等到服务器回复。聊天交还人。脚本没有改。",
                )
            last_server = batch.text
            last_id = batch.last_id
            echo(f"服务器：{_one_line(last_server)}")
            index += 1
            continue
        if not is_human_gate(last_server):
            return RunResult(
                "handed_back",
                "退回：脚本在等人，聊天里却没有须由人决定的卡片。聊天交还人。脚本没有改。",
            )
        echo("停下等你。请在 Telegram 里只回复 1、2 或 3。")
        got = transport.wait_human_choice(last_id, human_timeout)
        if got is None:
            return RunResult(
                "handed_back",
                "退回：没有等到单独的 1、2 或 3。聊天交还人。脚本没有改。",
            )
        choice, hid = got
        batch = transport.wait_server(hid, server_timeout)
        if choice == "3":
            return RunResult("stopped", "已停下，聊天交还人。脚本没有改。")
        if batch is None or not batch.messages:
            return RunResult(
                "handed_back",
                "退回：人已经选择，但没有等到服务器回复。聊天交还人。脚本没有改。",
            )
        last_server = batch.text
        last_id = batch.last_id
        echo(f"服务器：{_one_line(last_server)}")
        if choice == "2":
            if not op.redo:
                return RunResult("handed_back", "选了 2，脚本没有重做行。聊天交还人。脚本没有改。")
            if is_human_gate(last_server):
                return RunResult(
                    "handed_back",
                    "退回：选了 2 之后卡片还在，脚本不代答。聊天交还人。脚本没有改。",
                )
            echo(f"发送：{op.redo}")
            mid = transport.send(op.redo)
            redo_batch = transport.wait_server(mid, server_timeout)
            if redo_batch is None or not redo_batch.messages:
                return RunResult(
                    "handed_back",
                    "退回：重做之后没有等到服务器回复。聊天交还人。脚本没有改。",
                )
            last_server = redo_batch.text
            last_id = redo_batch.last_id
            echo(f"服务器：{_one_line(last_server)}")
            continue
        index += 1
    if is_human_gate(last_server):
        return RunResult("handed_back", "脚本走完了，聊天里还有须由人决定的问题，已交还人。脚本没有改。")
    return RunResult("finished", "脚本已发送完。成不成功以聊天里人的选择为准。")


def _one_line(text: str) -> str:
    return " ".join(text.split())
