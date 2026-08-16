"""Сессии CRM и проверка Telegram Web App."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from urllib.parse import parse_qsl

from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

import crud
from config import (
    ADMIN_TG_IDS,
    BOT_TOKEN,
    CRM_SESSION_HOURS,
    CRM_SESSION_SECRET,
    INTERNAL_API_SECRET,
)
from db.database import get_db
from db.models import Customer, StaffRole, User

COOKIE_NAME = "crm_token"
CRM_ROLES = {StaffRole.admin, StaffRole.operator, StaffRole.booker}
CASHIER_ROLES = {StaffRole.cashier, StaffRole.admin}
TG_INIT_DATA_MAX_AGE_SEC = 24 * 3600


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    pad = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + pad)


def create_session_token(user: User) -> str:
    """Подписанный токен сессии: uid + срок жизни."""
    payload = {
        "uid": user.id,
        "exp": int(time.time()) + CRM_SESSION_HOURS * 3600,
    }
    body = _b64url(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    sig = _b64url(
        hmac.new(CRM_SESSION_SECRET.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest()
    )
    return f"{body}.{sig}"


def parse_session_token(token: str) -> int | None:
    """Возвращает user id или None, если токен битый/просрочен."""
    try:
        body, sig = token.split(".", 1)
    except ValueError:
        return None
    expected = _b64url(
        hmac.new(CRM_SESSION_SECRET.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest()
    )
    if len(sig) != len(expected) or not hmac.compare_digest(sig, expected):
        return None
    try:
        payload = json.loads(_b64url_decode(body))
    except Exception:
        return None
    try:
        exp = int(payload.get("exp", 0))
        uid = payload.get("uid")
    except (TypeError, ValueError):
        return None
    if exp < time.time() or not isinstance(uid, int):
        return None
    return uid


def extract_token(request: Request) -> str | None:
    header = request.headers.get("authorization") or ""
    if header.lower().startswith("bearer "):
        token = header[7:].strip()
        if token:
            return token
    cookie = request.cookies.get(COOKIE_NAME)
    return cookie or None


def _cookie_secure(request: Request) -> bool:
    proto = (request.headers.get("x-forwarded-proto") or request.url.scheme or "").lower()
    return proto == "https"


def set_session_cookie(request: Request, response: Response, token: str) -> None:
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        secure=_cookie_secure(request),
        max_age=CRM_SESSION_HOURS * 3600,
        path="/",
    )


def clear_session_cookie(request: Request, response: Response) -> None:
    response.delete_cookie(
        key=COOKIE_NAME,
        path="/",
        samesite="lax",
        secure=_cookie_secure(request),
    )


def is_internal_request(request: Request) -> bool:
    """Бот стучится с заголовком X-Internal-Token."""
    given = request.headers.get("x-internal-token") or ""
    expected = INTERNAL_API_SECRET or ""
    if not expected or not given or len(given) != len(expected):
        return False
    return secrets.compare_digest(given, expected)


def get_current_crm_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User:
    token = extract_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="Требуется авторизация")
    user_id = parse_session_token(token)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Сессия недействительна или истекла")
    user = crud.get_staff_by_id(db, user_id)
    if (
        not user
        or not user.is_active
        or not user.password_hash
        or user.role not in CRM_ROLES
    ):
        raise HTTPException(status_code=401, detail="Сессия недействительна или истекла")
    return user


def require_roles(*roles: StaffRole):
    def _dependency(user: User = Depends(get_current_crm_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="Недостаточно прав")
        return user

    return _dependency


require_admin = require_roles(StaffRole.admin)
require_bookings_read = require_roles(
    StaffRole.admin, StaffRole.operator, StaffRole.booker
)
require_bookings_write = require_roles(StaffRole.admin, StaffRole.booker)


def require_admin_or_internal(
    request: Request,
    db: Session = Depends(get_db),
) -> User | None:
    """Чтение настроек: админ CRM или внутренний секрет бота."""
    if is_internal_request(request):
        return None
    user = get_current_crm_user(request, db)
    if user.role != StaffRole.admin:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    return user


def require_internal(request: Request) -> bool:
    """Только внутренние вызовы бота."""
    if not is_internal_request(request):
        raise HTTPException(status_code=401, detail="Требуется авторизация")
    return True


# ══════════════════════════════════════════════
# TELEGRAM WEB APP
# ══════════════════════════════════════════════

@dataclass(frozen=True)
class TelegramWebUser:
    id: int
    username: str | None = None
    first_name: str | None = None


@dataclass(frozen=True)
class CashierContext:
    tg_id: int
    staff: User | None


def extract_init_data(request: Request) -> str | None:
    header = request.headers.get("authorization") or ""
    if header.lower().startswith("tma "):
        token = header[4:].strip()
        if token:
            return token
    raw = (request.headers.get("x-telegram-init-data") or "").strip()
    return raw or None


def parse_telegram_init_data(init_data: str) -> TelegramWebUser | None:
    """Проверяет HMAC initData и возвращает пользователя Telegram."""
    if not BOT_TOKEN or not init_data:
        return None
    try:
        parsed = dict(parse_qsl(init_data, keep_blank_values=True))
    except ValueError:
        return None
    received_hash = parsed.pop("hash", None)
    if not received_hash:
        return None
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))
    secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode("utf-8"), hashlib.sha256).digest()
    calculated = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    if len(calculated) != len(received_hash) or not hmac.compare_digest(calculated, received_hash):
        return None
    try:
        auth_date = int(parsed.get("auth_date") or 0)
    except (TypeError, ValueError):
        return None
    now = time.time()
    if auth_date <= 0 or auth_date > now + 60 or now - auth_date > TG_INIT_DATA_MAX_AGE_SEC:
        return None
    try:
        user = json.loads(parsed.get("user") or "")
        uid = user.get("id")
        if not isinstance(uid, int):
            uid = int(uid)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    username = user.get("username")
    first_name = user.get("first_name")
    return TelegramWebUser(
        id=uid,
        username=str(username) if username else None,
        first_name=str(first_name) if first_name else None,
    )


def get_telegram_user(request: Request) -> TelegramWebUser:
    init_data = extract_init_data(request)
    user = parse_telegram_init_data(init_data) if init_data else None
    if not user:
        raise HTTPException(
            status_code=401,
            detail="Откройте приложение через Telegram-бота",
        )
    return user


def require_cashier(
    request: Request,
    db: Session = Depends(get_db),
) -> CashierContext:
    """Касса: подписанный Telegram-пользователь с ролью кассира/админа."""
    tg_user = get_telegram_user(request)
    staff = crud.get_staff_by_tg_id(db, tg_user.id)
    if staff and staff.role in CASHIER_ROLES:
        return CashierContext(tg_id=tg_user.id, staff=staff)
    if tg_user.id in ADMIN_TG_IDS:
        return CashierContext(tg_id=tg_user.id, staff=staff)
    raise HTTPException(status_code=403, detail="Нет доступа к терминалу кассира")


def require_own_customer(
    customer_id: int,
    tg_user: TelegramWebUser = Depends(get_telegram_user),
    db: Session = Depends(get_db),
) -> Customer:
    """Клиентский кабинет: только своя анкета."""
    customer = crud.get_customer_by_id(db, customer_id)
    if not customer or customer.tg_id != tg_user.id:
        raise HTTPException(status_code=404, detail="Клиент не найден")
    return customer
