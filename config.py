import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
BASE_API_URL = os.getenv("BASE_API_URL", "http://127.0.0.1:8000")

# Публичный HTTPS-URL для Telegram Web App (на сервере задаётся в .env)
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://funky-town-kst.kz")

BOT_USERNAME = "funkytown_kz_bot"  # Без @

REGISTRATION_BONUS = 500  # Бонусы за регистрацию

# tg_id владельца системы — всегда имеет доступ к /cashier даже без записи в БД
ADMIN_TG_IDS: list[int] = []  # временно пусто для тестирования клиентского флоу