from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardRemove,
)
from aiogram.types.web_app_info import WebAppInfo
from config import WEBAPP_URL


def get_client_nav_keyboard(tg_id: int) -> ReplyKeyboardMarkup:
    """Постоянная панель клиента — только личный кабинет (ссылки url в reply-клавиатуре не поддерживаются API Telegram)."""
    return ReplyKeyboardMarkup(
        keyboard=[[
            KeyboardButton(
                text="🎢 Личный кабинет",
                web_app=WebAppInfo(url=f"{WEBAPP_URL}/static/client.html?tg_id={tg_id}")
            )
        ]],
        resize_keyboard=True,
    )


def get_client_welcome_inline_keyboard(tg_id: int, whatsapp_url: str | None = None) -> InlineKeyboardMarkup:
    """Под приветствием: WebApp кабинет и при необходимости ссылка на WhatsApp (reply-клавиатура не умеет url)."""
    rows: list[list[InlineKeyboardButton]] = [[
        InlineKeyboardButton(
            text="🎢 Личный кабинет",
            web_app=WebAppInfo(url=f"{WEBAPP_URL}/static/client.html?tg_id={tg_id}"),
        )
    ]]
    if whatsapp_url:
        rows.append([
            InlineKeyboardButton(text="💬 Перейти в WhatsApp", url=whatsapp_url),
        ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_cashier_nav_keyboard(tg_id: int) -> ReplyKeyboardMarkup:
    """Постоянная панель кассира — только терминал."""
    return ReplyKeyboardMarkup(
        keyboard=[[
            KeyboardButton(
                text="💻 Терминал кассира",
                web_app=WebAppInfo(url=f"{WEBAPP_URL}/static/cashier.html?tg_id={tg_id}")
            ),
        ]],
        resize_keyboard=True,
    )


def get_main_keyboard():
    """Убирает клавиатуру (обратная совместимость)."""
    return ReplyKeyboardRemove()


def get_client_webapp_keyboard(tg_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="🎢 Открыть личный кабинет",
            web_app=WebAppInfo(url=f"{WEBAPP_URL}/static/client.html?tg_id={tg_id}")
        )
    ]])


def get_cashier_webapp_keyboard(tg_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="💻 Открыть терминал",
            web_app=WebAppInfo(url=f"{WEBAPP_URL}/static/cashier.html?tg_id={tg_id}")
        )
    ]])


def get_register_webapp_keyboard(tg_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="🚀 Открыть анкету",
            web_app=WebAppInfo(url=f"{WEBAPP_URL}/static/register.html?tg_id={tg_id}")
        )
    ]])
