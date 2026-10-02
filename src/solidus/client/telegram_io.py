"""用户账号向机器人的私聊发命令。机器人看不到别的机器人。"""

from __future__ import annotations

import asyncio
import time

from solidus.client.runner import ServerBatch
from solidus.config import Settings
from solidus.server.cards import only_choice


class TelegramTransport:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._loop = asyncio.new_event_loop()
        self._client = None
        self._own: set[int] = set()
        self._peer = None

    def open(self) -> None:
        self._loop.run_until_complete(self._open())

    def close(self) -> None:
        if self._client is not None:
            self._loop.run_until_complete(self._client.disconnect())
        self._loop.close()

    def send(self, text: str) -> int:
        return self._loop.run_until_complete(self._send(text))

    def wait_server(self, after_id: int, timeout: float) -> ServerBatch | None:
        return self._loop.run_until_complete(self._wait_server(after_id, timeout))

    def wait_human_choice(self, after_id: int, timeout: float) -> tuple[str, int] | None:
        return self._loop.run_until_complete(self._wait_human(after_id, timeout))

    async def _open(self) -> None:
        username = self.settings.telegram_bot_username.lstrip("@")
        if not username:
            raise SystemExit("还没有 TELEGRAM_BOT_USERNAME。按 docs/配置.md 填写。")
        if not self.settings.telegram_api_id or not self.settings.telegram_api_hash:
            raise SystemExit("还没有 TELEGRAM_API_ID / TELEGRAM_API_HASH。按 docs/配置.md 填写。")
        from telethon import TelegramClient

        self.settings.ledger_dir.mkdir(parents=True, exist_ok=True)
        self._client = TelegramClient(
            self.settings.session_base,
            self.settings.telegram_api_id,
            self.settings.telegram_api_hash,
        )
        await self._client.connect()
        if not await self._client.is_user_authorized():
            raise SystemExit("用户会话还没登录。先运行：solidus client login")
        self._peer = await self._client.get_entity(username)

    async def _send(self, text: str) -> int:
        message = await self._client.send_message(self._peer, text)
        self._own.add(message.id)
        return message.id

    async def _wait_server(self, after_id: int, timeout: float) -> ServerBatch | None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            found = []
            async for message in self._client.iter_messages(self._peer, min_id=after_id, reverse=True):
                if message.out or not message.message:
                    continue
                found.append(message)
            if found:
                return ServerBatch(tuple(item.message for item in found), found[-1].id)
            await asyncio.sleep(0.5)
        return None

    async def _wait_human(self, after_id: int, timeout: float) -> tuple[str, int] | None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            async for message in self._client.iter_messages(self._peer, min_id=after_id, reverse=True):
                if not message.out or message.id in self._own or not message.message:
                    continue
                choice = only_choice(message.message)
                if choice:
                    return choice, message.id
            await asyncio.sleep(0.5)
        return None


async def login_user(settings: Settings) -> None:
    if not settings.telegram_api_id or not settings.telegram_api_hash:
        raise SystemExit("还没有 TELEGRAM_API_ID / TELEGRAM_API_HASH。按 docs/配置.md 填写。")
    from telethon import TelegramClient

    settings.ledger_dir.mkdir(parents=True, exist_ok=True)
    client = TelegramClient(settings.session_base, settings.telegram_api_id, settings.telegram_api_hash)
    await client.start()
    me = await client.get_me()
    print(f"已登录用户会话。用户 id {me.id}。私聊时把这个数字写入 TELEGRAM_CHAT_ID。")
    await client.disconnect()
