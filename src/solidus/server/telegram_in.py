"""入站只有 Telegram。不看发送者是不是客户端。"""

from __future__ import annotations

import asyncio
import logging
import threading

from telegram import Update
from telegram.ext import Application, ContextTypes, MessageHandler, filters

from solidus.config import Settings
from solidus.wiring import build_workflow

logger = logging.getLogger(__name__)


def run_bot(settings: Settings) -> None:
    workflow = build_workflow(settings)
    lock = threading.Lock()

    async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        del context
        if update.message is None or not update.message.text or update.effective_chat is None:
            return
        chat_id = str(update.effective_chat.id)
        if settings.telegram_chat_id and chat_id != settings.telegram_chat_id:
            return
        if not settings.telegram_chat_id:
            print(f"这个聊天的 id 是 {chat_id}。写入 .env 的 TELEGRAM_CHAT_ID 后就只认这个聊天。")

        def work() -> list[str]:
            with lock:
                return workflow.handle(chat_id, update.message.text or "")

        replies = await asyncio.to_thread(work)
        for reply in replies:
            await update.message.reply_text(reply)

    application = Application.builder().token(settings.telegram_bot_token).build()
    application.add_handler(MessageHandler(filters.TEXT | filters.COMMAND, on_message))
    application.run_polling(drop_pending_updates=True)


__all__ = ["run_bot", "logger"]
