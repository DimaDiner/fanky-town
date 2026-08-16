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

# Учётные записи CRM (логин + пароль). Создаются при первом запуске, если их ещё нет в БД.
CRM_ADMIN_LOGIN = os.getenv("CRM_ADMIN_LOGIN", "admin")
CRM_ADMIN_PASSWORD = os.getenv("CRM_ADMIN_PASSWORD", "admin485")
CRM_OPERATOR_LOGIN = os.getenv("CRM_OPERATOR_LOGIN", "operator")
CRM_OPERATOR_PASSWORD = os.getenv("CRM_OPERATOR_PASSWORD", "operator123")
CRM_BOOKER_LOGIN = os.getenv("CRM_BOOKER_LOGIN", "casher")
CRM_BOOKER_PASSWORD = os.getenv("CRM_BOOKER_PASSWORD", "cahser095")

# DEBUG=1 — открыть /docs. На проде не задавать.
DEBUG = os.getenv("DEBUG", "0") == "1"

# Подпись сессии CRM. Если не задана — производная от токена бота.
CRM_SESSION_SECRET = os.getenv("CRM_SESSION_SECRET") or (
    f"{BOT_TOKEN}-crm-session" if BOT_TOKEN else "dev-crm-session-secret"
)
CRM_SESSION_HOURS = int(os.getenv("CRM_SESSION_HOURS", "12"))

# Секрет для внутренних вызовов API (бот → настройки). Обязательно сменить на проде.
INTERNAL_API_SECRET = os.getenv("INTERNAL_API_SECRET") or "dev-internal-secret-change-me"