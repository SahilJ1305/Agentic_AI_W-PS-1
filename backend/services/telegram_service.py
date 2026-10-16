import os

from telegram import Update, Bot
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)


class TelegramService:
    def __init__(self):
        self.token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.application = None

        # Temporary storage for integration testing only.
        # We will move this to PostgreSQL later.
        self.participants = {}

    async def start_command(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ):
        user = update.effective_user
        chat = update.effective_chat
        message = update.effective_message

        if not user or not chat or not message:
            return

        self.participants[str(user.id)] = {
            "telegram_user_id": user.id,
            "chat_id": chat.id,
            "name": user.full_name,
            "username": user.username,
        }

        await message.reply_text(
            "Welcome to the AI Group Project Coordinator! 🤖\n\n"
            "You are registered for Telegram updates.\n"
            "You can now receive project task follow-ups."
        )

    async def handle_message(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ):
        message = update.effective_message
        user = update.effective_user

        if not message or not message.text or not user:
            return

        # We will connect the AI classifier here later.
        await message.reply_text(
            "Your message was received successfully. ✅\n"
            f"Message: {message.text}\n\n"
            "AI task interpretation will be added next."
        )

    async def start(self):
        if not self.token:
            raise RuntimeError(
                "TELEGRAM_BOT_TOKEN is missing from environment"
            )

        self.application = (
            Application.builder()
            .token(self.token)
            .build()
        )

        self.application.add_handler(
            CommandHandler("start", self.start_command)
        )

        self.application.add_handler(
            MessageHandler(
                filters.TEXT & ~filters.COMMAND,
                self.handle_message,
            )
        )

        await self.application.initialize()
        await self.application.start()

        if not self.application.updater:
            raise RuntimeError("Telegram updater is unavailable")

        await self.application.updater.start_polling()

    async def stop(self):
        if not self.application:
            return

        if self.application.updater and self.application.updater.running:
            await self.application.updater.stop()

        if self.application.running:
            await self.application.stop()

        await self.application.shutdown()
        self.application = None

    async def send_message(self, chat_id: int, text: str):
        if not self.token:
            raise RuntimeError("Telegram token is missing")

        async with Bot(token=self.token) as bot:
            return await bot.send_message(
                chat_id=chat_id,
                text=text,
            )


telegram_service = TelegramService()
