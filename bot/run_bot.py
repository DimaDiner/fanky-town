import asyncio
import logging
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand
from config import BOT_TOKEN
from bot.handlers import router


async def main():
    logging.basicConfig(level=logging.INFO)

    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()

    dp.include_router(router)

    # Регистрируем команды — отображаются в слэш-меню у поля ввода
    await bot.set_my_commands([
        BotCommand(command="start", description="Главная страница / мой кабинет"),
        BotCommand(command="cashier", description="Терминал кассира"),
    ])

    print("Bot started successfully...")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Бот остановлен")
