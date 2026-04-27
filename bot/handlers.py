import json
from aiogram import Router, F, Bot, types
from aiogram.filters import Command, CommandStart
from aiogram.filters.command import CommandObject
from aiogram.types import MenuButtonWebApp
from aiogram.types.web_app_info import WebAppInfo
import httpx
from config import BASE_API_URL, ADMIN_TG_IDS, WEBAPP_URL
from bot.keyboards import (
    get_client_nav_keyboard,
    get_client_welcome_inline_keyboard,
    get_cashier_nav_keyboard,
)

router = Router()


async def _get_staff(tg_id: int) -> dict | None:
    """Возвращает данные сотрудника из API или None если не найден."""
    if tg_id in ADMIN_TG_IDS:
        return {"name": "Администратор", "role": "admin"}
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{BASE_API_URL}/staff/tg/{tg_id}")
    return r.json() if r.status_code == 200 else None


async def _get_customer(tg_id: int) -> dict | None:
    """Возвращает данные клиента из API или None если не найден."""
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{BASE_API_URL}/customers/tg/{tg_id}")
    return r.json() if r.status_code == 200 else None


async def _get_whatsapp_url() -> str | None:
    """Возвращает ссылку на WhatsApp из настроек или None если не задана."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(f"{BASE_API_URL}/admin/settings/")
        if r.status_code == 200:
            url = (r.json().get("whatsapp_url") or "").strip()
            return url or None
    except Exception:
        pass
    return None


@router.message(CommandStart(deep_link=True))
async def cmd_start_invite(message: types.Message, command: CommandObject, bot: Bot):
    """Обрабатывает /start inv_TOKEN — подтверждение кассира по invite-ссылке."""
    arg = command.args or ""
    if not arg.startswith("inv_"):
        await _send_welcome(message, bot)
        return

    token = arg[4:]
    tg_user = message.from_user

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{BASE_API_URL}/staff/confirm/{token}",
            json={"tg_id": tg_user.id, "tg_username": tg_user.username}
        )

    if response.status_code == 200:
        staff = response.json()
        await message.answer(
            f"✅ *{staff['name']}, добро пожаловать!*\n\n"
            f"Ваш аккаунт подтверждён. Теперь вы можете принимать оплату бонусами через терминал.\n\n"
            f"Нажмите кнопку ниже, чтобы открыть терминал кассира 👇",
            parse_mode="Markdown",
            reply_markup=get_cashier_nav_keyboard(tg_user.id)
        )
        await bot.set_chat_menu_button(
            chat_id=message.chat.id,
            menu_button=MenuButtonWebApp(
                text="💻 Терминал",
                web_app=WebAppInfo(url=f"{WEBAPP_URL}/static/cashier.html?tg_id={tg_user.id}")
            )
        )
    elif response.status_code == 404:
        await message.answer("Ссылка недействительна или уже была использована.")
    else:
        await message.answer("Произошла ошибка при подтверждении. Обратитесь к администратору.")


@router.message(Command("start"))
async def cmd_start(message: types.Message, bot: Bot):
    await _send_welcome(message, bot)


async def _send_welcome(message: types.Message, bot: Bot):
    """
    Умное приветствие — поведение зависит от роли пользователя:
      • кассир   → панель с терминалом + кабинетом, MenuButton на терминал
      • клиент   → приветствие с балансом, панель с кабинетом
      • новичок  → онбординг с описанием программы, панель с кабинетом
    """
    tg_id = message.from_user.id
    first_name = message.from_user.first_name or "Гость"

    staff = await _get_staff(tg_id)
    customer = await _get_customer(tg_id)
    whatsapp_url = await _get_whatsapp_url()

    # ── Кассир ──────────────────────────────────────────────────────────
    if staff:
        name = staff.get("name") or first_name
        await message.answer(
            f"👋 Привет, *{name}*!\n\n"
            f"Вы вошли как *кассир Funky Town*.\n"
            f"Нажмите кнопку ниже, чтобы открыть терминал 👇",
            parse_mode="Markdown",
            reply_markup=get_cashier_nav_keyboard(tg_id)
        )
        await bot.set_chat_menu_button(
            chat_id=message.chat.id,
            menu_button=MenuButtonWebApp(
                text="💻 Терминал",
                web_app=WebAppInfo(url=f"{WEBAPP_URL}/static/cashier.html?tg_id={tg_id}")
            )
        )
        return

    # ── Зарегистрированный клиент ────────────────────────────────────────
    if customer:
        name = customer.get("full_name") or first_name
        balance = customer.get("balance", 0)
        text = (
            f"👋 С возвращением, *{name}*!\n\n"
            f"💳 На вашей карте: *{balance} бонусов*\n\n"
            f"Открывайте кабинет, чтобы смотреть историю операций 👇"
        )
    # ── Новый пользователь ───────────────────────────────────────────────
    else:
        text = (
            f"🎢 Привет, *{first_name}*! Добро пожаловать в *Funky Town*!\n\n"
            f"Это официальный бот нашего детского парка развлечений.\n"
            f"Здесь ты можешь:\n"
            f"  • Копить бонусы за каждое посещение\n"
            f"  • Оплачивать ими аттракционы (1 бонус = 1 тенге)\n"
            f"  • Получать подарки в день рождения ребёнка 🎁\n\n"
            f"Нажми кнопку ниже, чтобы создать карту — это займёт минуту 👇"
        )

    await message.answer(
        text,
        parse_mode="Markdown",
        reply_markup=get_client_welcome_inline_keyboard(tg_id, whatsapp_url),
    )
    # У одного sendMessage не может быть и inline, и reply-клавиатура: служебное сообщение сразу удаляем —
    # нижняя клавиатура в клиентах Telegram при этом обычно остаётся.
    kb_msg = await message.answer("\u2060", reply_markup=get_client_nav_keyboard(tg_id))
    try:
        await bot.delete_message(chat_id=kb_msg.chat.id, message_id=kb_msg.message_id)
    except Exception:
        pass
    await bot.set_chat_menu_button(
        chat_id=message.chat.id,
        menu_button=MenuButtonWebApp(
            text="🎢 Кабинет",
            web_app=WebAppInfo(url=f"{WEBAPP_URL}/static/client.html?tg_id={tg_id}")
        )
    )


@router.message(Command("cashier"))
async def cmd_cashier(message: types.Message, bot: Bot):
    tg_id = message.from_user.id
    staff = await _get_staff(tg_id)

    if staff:
        await message.answer(
            "💻 Терминал кассира:",
            reply_markup=get_cashier_nav_keyboard(tg_id)
        )
    else:
        await message.answer(
            "У вас нет доступа к терминалу кассира.\n"
            "Если вы сотрудник — попросите администратора выслать вам ссылку для подтверждения."
        )


@router.message(F.web_app_data)
async def on_webapp_data(message: types.Message):
    """Резервный обработчик данных из WebApp (если WebApp вызовет tg.sendData)."""
    try:
        data = json.loads(message.web_app_data.data)
        if data.get("status") == "registered":
            balance = data.get("balance", 0)
            name = data.get("name") or "Гость"
            await message.answer(
                f"*{name}, добро пожаловать в Funky Town!*\n\n"
                f"На счёт зачислено *{balance} приветственных бонусов*",
                parse_mode="Markdown"
            )
    except (json.JSONDecodeError, KeyError):
        pass
