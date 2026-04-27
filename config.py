import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
BASE_API_URL = "http://127.0.0.1:8000"

WEBAPP_URL = "https://dc8f-188-130-156-242.ngrok-free.app"  # Обновляй при каждом перезапуске ngrok

BOT_USERNAME = "funkytown_kz_bot"  # Без @

REGISTRATION_BONUS = 500  # Бонусы за регистрацию

# tg_id владельца системы — всегда имеет доступ к /cashier даже без записи в БД
ADMIN_TG_IDS: list[int] = []  # временно пусто для тестирования клиентского флоу