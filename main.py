from fastapi.staticfiles import StaticFiles
from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks, Form, UploadFile, File
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from sqlalchemy import text
from contextlib import asynccontextmanager
import secrets
import json
import httpx
from db.database import engine, Base, get_db, SessionLocal
import db.models as models
import schemas
import crud
from config import BOT_TOKEN, BOT_USERNAME


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Добавляем новые колонки в users если их ещё нет (safe migration)."""
    with engine.connect() as conn:
        for stmt in [
            "ALTER TABLE users ADD COLUMN tg_username VARCHAR",
            "ALTER TABLE users ADD COLUMN invite_token VARCHAR",
            "ALTER TABLE users ADD COLUMN username VARCHAR",
            "ALTER TABLE users ADD COLUMN password_hash VARCHAR",
            "UPDATE bookings SET package = 'lite' WHERE package IN ('super', 'premium')",
        ]:
            try:
                conn.execute(text(stmt))
                conn.commit()
            except Exception:
                pass  # колонка уже существует

    db = SessionLocal()
    try:
        crud.ensure_default_crm_users(db)
    finally:
        db.close()

    yield


models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="Funky Town Bonus API", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")


def notify_customer(tg_id: int, amount: int, new_balance: int):
    """Отправляет клиенту уведомление о списании бонусов."""
    if not tg_id:
        return
    text = (
        f"💸 *Списание бонусов*\n\n"
        f"С вашей карты Funky Town списано: *{abs(amount)} бонусов*\n"
        f"Остаток на счёте: *{new_balance} бонусов*\n\n"
        f"Спасибо за посещение! 🎢"
    )
    try:
        httpx.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": tg_id, "text": text, "parse_mode": "Markdown"},
            timeout=5.0
        )
    except Exception:
        pass


def notify_accrual(tg_id: int, amount: int, new_balance: int):
    """Отправляет клиенту уведомление о начислении бонусов."""
    if not tg_id:
        return
    text = (
        f"🎁 *Начисление бонусов*\n\n"
        f"На вашу карту Funky Town начислено: *{amount} бонусов*\n"
        f"Баланс на счёте: *{new_balance} бонусов*\n\n"
        f"Используйте бонусы при следующем посещении! 🎢"
    )
    try:
        httpx.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": tg_id, "text": text, "parse_mode": "Markdown"},
            timeout=5.0
        )
    except Exception:
        pass


# --- ЭНДПОИНТЫ ---

@app.post("/customers/", response_model=schemas.CustomerResponse)
def create_customer(customer: schemas.CustomerCreate, db: Session = Depends(get_db)):
    db_customer = crud.get_customer_by_phone(db, phone=customer.phone)
    if db_customer:
        raise HTTPException(status_code=400, detail="Этот телефон уже зарегистрирован")
    return crud.create_customer(db=db, customer=customer)


@app.get("/customers/tg/{tg_id}", response_model=schemas.CustomerResponse)
def read_customer_by_tg(tg_id: int, db: Session = Depends(get_db)):
    db_customer = crud.get_customer_by_tg_id(db, tg_id=tg_id)
    if db_customer is None:
        raise HTTPException(status_code=404, detail="Клиент не найден")
    return db_customer


@app.get("/customers/{phone}", response_model=schemas.CustomerResponse)
def read_customer(phone: str, db: Session = Depends(get_db)):
    db_customer = crud.get_customer_by_phone(db, phone=phone)
    if db_customer is None:
        raise HTTPException(status_code=404, detail="Клиент не найден")
    return db_customer


@app.post("/transactions/", response_model=schemas.TransactionResponse)
def make_transaction(
    trans: schemas.TransactionCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    result = crud.process_transaction(db, trans)
    if result is None:
        raise HTTPException(status_code=404, detail="Клиент не найден")
    if result == "insufficient_balance":
        raise HTTPException(status_code=400, detail="Недостаточно бонусов на счёте")

    if result.tg_id and trans.amount < 0:
        background_tasks.add_task(notify_customer, result.tg_id, trans.amount, result.balance)

    return {
        "id": result.id,
        "new_balance": result.balance,
        "status": "success"
    }


@app.patch("/customers/{customer_id}/profile", response_model=schemas.CustomerResponse)
def update_customer_profile(customer_id: int, data: schemas.CustomerProfileUpdate, db: Session = Depends(get_db)):
    customer = crud.update_customer_profile(db, customer_id, data.full_name)
    if not customer:
        raise HTTPException(status_code=404, detail="Клиент не найден")
    return customer


@app.post("/customers/{customer_id}/kids", response_model=schemas.KidResponse)
def add_kid(customer_id: int, kid: schemas.KidCreate, db: Session = Depends(get_db)):
    result = crud.add_kid_to_customer(db, customer_id, kid)
    if not result:
        raise HTTPException(status_code=404, detail="Клиент не найден")
    return result


@app.get("/customers/{customer_id}/transactions", response_model=list[schemas.TransactionHistoryItem])
def get_transactions(customer_id: int, limit: int = 10, db: Session = Depends(get_db)):
    return crud.get_customer_transactions(db, customer_id, limit)


# --- ПЕРСОНАЛ (для бота) ---

@app.get("/staff/tg/{tg_id}", response_model=schemas.StaffResponse)
def get_staff_by_tg(tg_id: int, db: Session = Depends(get_db)):
    """Бот проверяет роль пользователя перед открытием терминала."""
    staff = crud.get_staff_by_tg_id(db, tg_id)
    if not staff:
        raise HTTPException(status_code=404, detail="Сотрудник не найден")
    return staff


@app.post("/staff/confirm/{token}", response_model=schemas.StaffResponse)
def confirm_invite(token: str, body: schemas.StaffConfirm, db: Session = Depends(get_db)):
    """Кассир перешёл по invite-ссылке — фиксируем его tg_id."""
    staff = crud.get_staff_by_token(db, token)
    if not staff:
        raise HTTPException(status_code=404, detail="Ссылка недействительна или уже использована")
    if staff.tg_id and staff.tg_id != body.tg_id:
        raise HTTPException(status_code=400, detail="Ссылка привязана к другому аккаунту")
    return crud.confirm_staff_invite(db, staff, body.tg_id, body.tg_username)


# --- АДМИНКА ---

@app.get("/admin/")
def admin_panel():
    return FileResponse("static/admin.html")


@app.get("/admin/stats/", response_model=schemas.AdminStatsExtended)
def admin_stats(db: Session = Depends(get_db)):
    return crud.get_admin_stats(db)


@app.get("/admin/customers/", response_model=list[schemas.AdminCustomerItem])
def admin_customers(search: str = None, db: Session = Depends(get_db)):
    return crud.get_all_customers_admin(db, search)


@app.get("/admin/transactions/", response_model=schemas.AdminTransactionPage)
def admin_transactions(
    page: int = 1,
    per_page: int = 25,
    search: str = None,
    tx_type: str = None,
    date_from: str = None,
    date_to: str = None,
    export: bool = False,
    db: Session = Depends(get_db),
):
    return crud.get_all_transactions_admin(
        db,
        page=page,
        per_page=per_page,
        search=search,
        tx_type=tx_type,
        date_from=date_from,
        date_to=date_to,
        export=export,
    )


@app.get("/admin/staff/", response_model=list[schemas.StaffResponse])
def list_staff(db: Session = Depends(get_db)):
    return crud.get_all_staff(db)


@app.post("/admin/staff/", response_model=schemas.StaffInviteResponse)
def create_staff(staff: schemas.StaffCreate, db: Session = Depends(get_db)):
    token = secrets.token_urlsafe(16)
    db_user = crud.create_staff(db, staff, token)
    invite_link = f"https://t.me/{BOT_USERNAME}?start=inv_{token}"
    return schemas.StaffInviteResponse(
        **schemas.StaffResponse.model_validate(db_user).model_dump(),
        invite_link=invite_link
    )


@app.patch("/admin/staff/{staff_id}/deactivate", response_model=schemas.StaffResponse)
def deactivate_staff(staff_id: int, db: Session = Depends(get_db)):
    staff = crud.deactivate_staff(db, staff_id)
    if not staff:
        raise HTTPException(status_code=404, detail="Сотрудник не найден")
    return staff


@app.get("/admin/settings/")
def get_settings(db: Session = Depends(get_db)):
    """Возвращает все системные настройки."""
    return crud.get_all_settings(db)


@app.patch("/admin/settings/{key}")
def update_setting(key: str, body: schemas.SettingUpdate, db: Session = Depends(get_db)):
    """Обновляет значение настройки."""
    from urllib.parse import urlparse
    allowed_keys = {"registration_bonus", "whatsapp_url"}
    if key not in allowed_keys:
        raise HTTPException(status_code=400, detail="Неизвестный ключ настройки")
    if key == "registration_bonus":
        try:
            val = int(body.value)
            if val < 0:
                raise ValueError
        except ValueError:
            raise HTTPException(status_code=400, detail="Значение должно быть целым числом ≥ 0")
    if key == "whatsapp_url" and body.value:
        parsed = urlparse(body.value)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise HTTPException(status_code=400, detail="Введите корректный адрес")
    crud.set_setting(db, key, body.value)
    return {"key": key, "value": body.value}


@app.post("/admin/bonus/accrue", response_model=schemas.BonusAccrueResponse)
def accrue_bonus(
    req: schemas.BonusAccrueRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """Начисляет бонусы выбранным клиентам и отправляет им уведомления."""
    if req.amount <= 0:
        raise HTTPException(status_code=400, detail="Сумма должна быть больше 0")
    if not req.customer_ids:
        raise HTTPException(status_code=400, detail="Список клиентов пуст")

    customers = crud.accrue_bonus_bulk(db, req.customer_ids, req.amount)
    for c in customers:
        if c.tg_id:
            background_tasks.add_task(notify_accrual, c.tg_id, req.amount, c.balance)

    return {
        "accrued_count": len(customers),
        "total_amount": req.amount * len(customers)
    }


def send_tg_broadcast(tg_id: int, message: str, photo_bytes: bytes | None) -> bool:
    """Отправляет рекламное сообщение клиенту через Telegram."""
    try:
        if photo_bytes:
            resp = httpx.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto",
                data={"chat_id": tg_id, "caption": message, "parse_mode": "Markdown"},
                files={"photo": ("image.jpg", photo_bytes, "image/jpeg")},
                timeout=10.0,
            )
        else:
            resp = httpx.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                json={"chat_id": tg_id, "text": message, "parse_mode": "Markdown"},
                timeout=10.0,
            )
        return resp.status_code == 200
    except Exception:
        return False


@app.post("/admin/broadcast/", response_model=schemas.BroadcastResponse)
async def send_broadcast(
    customer_ids: str = Form(...),
    message: str = Form(...),
    image: UploadFile = File(None),
    db: Session = Depends(get_db),
):
    """Отправляет рекламное сообщение выбранным клиентам в Telegram."""
    try:
        ids = json.loads(customer_ids)
        if not isinstance(ids, list):
            raise ValueError
    except Exception:
        raise HTTPException(status_code=400, detail="Неверный формат списка клиентов")

    if not ids:
        raise HTTPException(status_code=400, detail="Список клиентов пуст")
    if not message.strip():
        raise HTTPException(status_code=400, detail="Текст сообщения не может быть пустым")

    photo_bytes: bytes | None = None
    if image and image.filename:
        photo_bytes = await image.read()

    customers = db.query(models.Customer).filter(models.Customer.id.in_(ids)).all()

    sent = 0
    failed = 0
    no_tg = 0

    for c in customers:
        if not c.tg_id:
            no_tg += 1
            continue
        if send_tg_broadcast(c.tg_id, message, photo_bytes):
            sent += 1
        else:
            failed += 1

    return {
        "sent_count": sent,
        "failed_count": failed,
        "no_tg_count": no_tg,
        "total": len(customers),
    }


# ══════════════════════════════════════════════
# АВТОРИЗАЦИЯ CRM
# ══════════════════════════════════════════════

@app.post("/admin/auth/", response_model=schemas.CRMUserResponse)
def crm_auth(body: schemas.CRMLoginRequest, db: Session = Depends(get_db)):
    """
    Авторизация в CRM по логину и паролю.
    Доступ разрешён для ролей: admin, operator, booker.
    """
    staff = crud.authenticate_crm_user(db, body.username, body.password)
    if not staff:
        raise HTTPException(status_code=403, detail="Неверный логин или пароль")
    return staff


# ══════════════════════════════════════════════
# БРОНИРОВАНИЯ
# ══════════════════════════════════════════════

@app.get("/admin/bookings/check-conflict", response_model=schemas.BookingConflictResponse)
def check_booking_conflict(
    date: str,
    time_start: str,
    time_end: str,
    exclude_id: int = None,
    db: Session = Depends(get_db),
):
    """
    Проверяет конфликт времени до создания/обновления брони.
    Используется фронтендом для real-time валидации.
    Параметры: date (YYYY-MM-DD), time_start (HH:MM), time_end (HH:MM), exclude_id (опционально).
    """
    from datetime import date as _date
    try:
        booking_date = _date.fromisoformat(date)
    except ValueError:
        raise HTTPException(status_code=422, detail="Неверный формат даты (ожидается YYYY-MM-DD)")

    conflict = crud.check_time_conflict(db, booking_date, time_start, time_end, exclude_id)
    if conflict:
        return {"conflict": True, "conflicting_booking": conflict}
    return {"conflict": False, "conflicting_booking": None}


@app.get("/admin/bookings/", response_model=list[schemas.BookingListItem])
def list_bookings(
    year: int = None,
    month: int = None,
    db: Session = Depends(get_db),
):
    """
    Возвращает все брони за указанный месяц.
    По умолчанию — текущий месяц.
    """
    from datetime import date as _date
    today = _date.today()
    y = year  if year  else today.year
    m = month if month else today.month
    if not (1 <= m <= 12):
        raise HTTPException(status_code=422, detail="Месяц должен быть от 1 до 12")
    return crud.get_bookings_by_month(db, y, m)


@app.post("/admin/bookings/", response_model=schemas.BookingResponse, status_code=201)
def create_booking(booking: schemas.BookingCreate, db: Session = Depends(get_db)):
    """Создаёт новое бронирование. Статус выбирается администратором (по умолчанию draft)."""
    try:
        return crud.create_booking(db, booking)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@app.get("/admin/bookings/{booking_id}", response_model=schemas.BookingResponse)
def get_booking(booking_id: int, db: Session = Depends(get_db)):
    booking = crud.get_booking_by_id(db, booking_id)
    if not booking:
        raise HTTPException(status_code=404, detail="Бронирование не найдено")
    return booking


@app.patch("/admin/bookings/{booking_id}", response_model=schemas.BookingResponse)
def update_booking(booking_id: int, data: schemas.BookingUpdate, db: Session = Depends(get_db)):
    """Обновляет любые поля брони. Все поля опциональны."""
    try:
        booking = crud.update_booking(db, booking_id, data)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    if not booking:
        raise HTTPException(status_code=404, detail="Бронирование не найдено")
    return booking


@app.patch("/admin/bookings/{booking_id}/status", response_model=schemas.BookingResponse)
def update_booking_status(
    booking_id: int,
    data: schemas.BookingStatusUpdate,
    db: Session = Depends(get_db),
):
    """Быстрая смена статуса без передачи всех полей. Все переходы разрешены."""
    booking = crud.update_booking_status(db, booking_id, data.status)
    if not booking:
        raise HTTPException(status_code=404, detail="Бронирование не найдено")
    return booking


@app.delete("/admin/bookings/{booking_id}")
def delete_booking(booking_id: int, db: Session = Depends(get_db)):
    """
    Мягкое удаление: переводит бронь в статус 'cancelled'.
    Запись физически не удаляется из БД.
    """
    success = crud.delete_booking(db, booking_id)
    if not success:
        raise HTTPException(status_code=404, detail="Бронирование не найдено")
    return {"ok": True}

