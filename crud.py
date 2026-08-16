import hashlib
import secrets

from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, date
import calendar
from db.models import Customer, Kid, Transaction, TransactionType, User, Setting, Booking, BookingStatus, StaffRole
import schemas
from config import (
    REGISTRATION_BONUS,
    CRM_ADMIN_LOGIN,
    CRM_ADMIN_PASSWORD,
    CRM_OPERATOR_LOGIN,
    CRM_OPERATOR_PASSWORD,
    CRM_BOOKER_LOGIN,
    CRM_BOOKER_PASSWORD,
)

# --- НАСТРОЙКИ ---

def get_setting(db: Session, key: str, default: str = "") -> str:
    row = db.query(Setting).filter(Setting.key == key).first()
    return row.value if row else default

def set_setting(db: Session, key: str, value: str) -> Setting:
    row = db.query(Setting).filter(Setting.key == key).first()
    if row:
        row.value = value
    else:
        row = Setting(key=key, value=value)
        db.add(row)
    db.commit()
    return row

def get_registration_bonus(db: Session) -> int:
    """Возвращает бонус за регистрацию из БД; при первом вызове инициализирует из config."""
    row = db.query(Setting).filter(Setting.key == "registration_bonus").first()
    if row is None:
        row = Setting(key="registration_bonus", value=str(REGISTRATION_BONUS))
        db.add(row)
        db.commit()
    return int(row.value)

def get_bonus_ttl_months(db: Session) -> int:
    """Возвращает срок жизни бонусов в месяцах; при первом вызове инициализирует значением 3."""
    row = db.query(Setting).filter(Setting.key == "bonus_ttl_months").first()
    if row is None:
        row = Setting(key="bonus_ttl_months", value="3")
        db.add(row)
        db.commit()
    return int(row.value)


def _add_calendar_months(dt: datetime, months: int) -> datetime:
    """Добавляет календарные месяцы к дате (с учётом коротких месяцев)."""
    month = dt.month - 1 + months
    year = dt.year + month // 12
    month = month % 12 + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def compute_expires_at(db: Session) -> datetime | None:
    """Срок протухания нового начисления: сейчас UTC + bonus_ttl_months. TTL=0 → None."""
    ttl = get_bonus_ttl_months(db)
    if ttl <= 0:
        return None
    return _add_calendar_months(datetime.utcnow(), ttl)


def _fifo_batch_remainders(transactions: list[Transaction]) -> list[tuple[Transaction, int]]:
    """
    Распределяет отрицательные транзакции (касса, expiry) по партиям начисления FIFO.
    Возвращает список (партия, остаток) в порядке от старых к новым.
    """
    batches: list[tuple[Transaction, int]] = []
    for tx in sorted(transactions, key=lambda t: (t.created_at, t.id)):
        if tx.amount > 0:
            batches.append((tx, tx.amount))
        elif tx.amount < 0:
            to_allocate = abs(tx.amount)
            for i, (batch_tx, remaining) in enumerate(batches):
                if to_allocate <= 0:
                    break
                if remaining <= 0:
                    continue
                deduct = min(remaining, to_allocate)
                batches[i] = (batch_tx, remaining - deduct)
                to_allocate -= deduct
    return batches


def expire_overdue_bonuses(db: Session) -> int:
    """
    Списывает просроченные неиспользованные бонусы транзакциями типа expiry.
    FIFO: расходы распределяются по партиям от старых к новым; сторно = остаток партии.
    Партии с expires_at IS NULL не затрагиваются. Идемпотентно при повторном запуске.
    Возвращает число созданных транзакций сторно (списанных партий).
    """
    now = datetime.utcnow()
    expired_count = 0

    customers = db.query(Customer).all()
    for customer in customers:
        transactions = (
            db.query(Transaction)
            .filter(Transaction.customer_id == customer.id)
            .order_by(Transaction.created_at, Transaction.id)
            .all()
        )
        batches = _fifo_batch_remainders(transactions)
        current_balance = customer.balance
        customer_changed = False

        for batch_tx, remaining in batches:
            if remaining <= 0:
                continue
            if batch_tx.expires_at is None or batch_tx.expires_at > now:
                continue
            if batch_tx.type == TransactionType.expiry:
                continue

            expire_amount = min(remaining, current_balance)
            if expire_amount <= 0:
                continue

            db.add(Transaction(
                customer_id=customer.id,
                cashier_id=None,
                amount=-expire_amount,
                type=TransactionType.expiry,
                expires_at=None,
            ))
            current_balance -= expire_amount
            expired_count += 1
            customer_changed = True

        if customer_changed:
            customer.balance = current_balance

    if expired_count > 0:
        db.commit()

    return expired_count


def backfill_transaction_expires_at(db: Session) -> int:
    """
    Разовая простановка expires_at для старых начислений без срока.
    Идемпотентно: уже заполненные expires_at не трогаются.
    """
    expires_at = compute_expires_at(db)
    if expires_at is None:
        return 0

    rows = (
        db.query(Transaction)
        .filter(Transaction.amount > 0, Transaction.expires_at.is_(None))
        .all()
    )
    for tx in rows:
        tx.expires_at = expires_at
    if rows:
        db.commit()
    return len(rows)


def get_all_settings(db: Session) -> dict:
    rows = db.query(Setting).all()
    result = {
        "registration_bonus": str(REGISTRATION_BONUS),
        "bonus_ttl_months": "3",
    }
    result.update({r.key: r.value for r in rows})
    return result

# 1. Найти клиента по телефону
def get_customer_by_phone(db: Session, phone: str):
    return db.query(Customer).filter(Customer.phone == phone).first()

# 2. Найти клиента по Telegram ID
def get_customer_by_tg_id(db: Session, tg_id: int):
    return db.query(Customer).filter(Customer.tg_id == tg_id).first()

# 3. Создать нового клиента (Регистрация)
def create_customer(db: Session, customer: schemas.CustomerCreate):
    reg_bonus = get_registration_bonus(db)

    db_customer = Customer(
        phone=customer.phone,
        full_name=customer.full_name,
        tg_id=customer.tg_id,
        balance=reg_bonus
    )
    db.add(db_customer)
    db.commit()
    db.refresh(db_customer)

    for kid_data in customer.kids:
        db_kid = Kid(
            customer_id=db_customer.id,
            name=kid_data.name,
            gender=kid_data.gender,
            birth_date=kid_data.birth_date
        )
        db.add(db_kid)

    if reg_bonus > 0:
        db.add(Transaction(
            customer_id=db_customer.id,
            cashier_id=None,
            amount=reg_bonus,
            type=TransactionType.registration,
            expires_at=compute_expires_at(db),
        ))

    db.commit()
    db.refresh(db_customer)
    return db_customer

# 4. Обновить имя клиента
def update_customer_profile(db: Session, customer_id: int, full_name: str | None) -> Customer | None:
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        return None
    if full_name is not None:
        customer.full_name = full_name
    db.commit()
    db.refresh(customer)
    return customer


# 5. Добавить ребёнка к клиенту (birth_date устанавливается один раз — не изменяется через этот метод)
def add_kid_to_customer(db: Session, customer_id: int, kid_data: schemas.KidCreate) -> Kid | None:
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        return None
    db_kid = Kid(
        customer_id=customer_id,
        name=kid_data.name,
        gender=kid_data.gender,
        birth_date=kid_data.birth_date,
    )
    db.add(db_kid)
    db.commit()
    db.refresh(db_kid)
    return db_kid


# --- ПЕРСОНАЛ ---

def _hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), 100_000
    )
    return f"{salt}${digest.hex()}"


def _verify_password(password: str, password_hash: str) -> bool:
    if not password_hash or "$" not in password_hash:
        return False
    salt, expected = password_hash.split("$", 1)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), 100_000
    )
    return secrets.compare_digest(digest.hex(), expected)


def get_staff_by_username(db: Session, username: str) -> User | None:
    login = username.strip().lower()
    if not login:
        return None
    return (
        db.query(User)
        .filter(User.username == login, User.is_active == True)
        .first()
    )


def authenticate_crm_user(db: Session, username: str, password: str) -> User | None:
    user = get_staff_by_username(db, username)
    if not user or not user.password_hash:
        return None
    if user.role not in (StaffRole.admin, StaffRole.operator, StaffRole.booker):
        return None
    if not _verify_password(password, user.password_hash):
        return None
    return user


def ensure_default_crm_users(db: Session) -> None:
    """Создаёт учётные записи admin, operator и booker, если их ещё нет."""
    defaults = (
        (CRM_ADMIN_LOGIN, CRM_ADMIN_PASSWORD, StaffRole.admin, "Администратор"),
        (CRM_OPERATOR_LOGIN, CRM_OPERATOR_PASSWORD, StaffRole.operator, "Оператор"),
        (CRM_BOOKER_LOGIN, CRM_BOOKER_PASSWORD, StaffRole.booker, "Кассир"),
    )
    created = False
    for login, password, role, name in defaults:
        login = login.strip().lower()
        if not login or not password:
            continue
        exists = db.query(User).filter(User.username == login).first()
        if exists:
            continue
        db.add(User(
            username=login,
            password_hash=_hash_password(password),
            name=name,
            role=role,
            is_active=True,
        ))
        created = True
    if created:
        db.commit()


def create_staff(db: Session, staff: schemas.StaffCreate, invite_token: str) -> User:
    db_user = User(
        name=staff.name,
        tg_username=staff.tg_username.lstrip("@"),
        role=staff.role,
        invite_token=invite_token,
        is_active=False,
        tg_id=None,
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user


def get_staff_by_token(db: Session, token: str) -> User | None:
    return db.query(User).filter(User.invite_token == token).first()


def confirm_staff_invite(db: Session, user: User, tg_id: int, tg_username: str | None) -> User:
    user.tg_id = tg_id
    if tg_username:
        user.tg_username = tg_username
    user.is_active = True
    user.invite_token = None  # токен одноразовый
    db.commit()
    db.refresh(user)
    return user


def get_staff_by_tg_id(db: Session, tg_id: int) -> User | None:
    return db.query(User).filter(User.tg_id == tg_id, User.is_active == True).first()


def get_all_staff(db: Session) -> list[User]:
    return db.query(User).order_by(User.created_at.desc()).all()


def deactivate_staff(db: Session, staff_id: int) -> User | None:
    user = db.query(User).filter(User.id == staff_id).first()
    if user:
        user.is_active = False
        db.commit()
        db.refresh(user)
    return user


# --- ТРАНЗАКЦИИ ---

def get_customer_transactions(db: Session, customer_id: int, limit: int = 10):
    return (
        db.query(Transaction)
        .filter(Transaction.customer_id == customer_id)
        .order_by(Transaction.created_at.desc())
        .limit(limit)
        .all()
    )


# --- АДМИНКА ---

def get_admin_stats(db: Session) -> dict:
    today_start = datetime.combine(date.today(), datetime.min.time())

    total_customers  = db.query(Customer).count()
    active_cashiers  = db.query(User).filter(User.is_active == True).count()
    total_balance    = db.query(func.sum(Customer.balance)).scalar() or 0

    issued_today = db.query(func.sum(Transaction.amount)).filter(
        Transaction.amount > 0,
        Transaction.created_at >= today_start
    ).scalar() or 0

    spent_today = db.query(func.sum(Transaction.amount)).filter(
        Transaction.amount < 0,
        Transaction.created_at >= today_start
    ).scalar() or 0

    # Статистика бронирований
    booking_stats = get_bookings_stats(db)

    return {
        "total_customers":      total_customers,
        "active_cashiers":      active_cashiers,
        "bonuses_issued_today": int(issued_today),
        "bonuses_spent_today":  abs(int(spent_today)),
        "total_bonus_balance":  int(total_balance),
        **booking_stats,
    }


def get_all_customers_admin(db: Session, search: str | None = None) -> list[dict]:
    query = db.query(Customer)
    if search:
        query = query.filter(
            Customer.full_name.ilike(f"%{search}%") |
            Customer.phone.ilike(f"%{search}%")
        )
    customers = query.order_by(Customer.created_at.desc()).all()
    return [
        {
            "id":         c.id,
            "full_name":  c.full_name,
            "phone":      c.phone,
            "tg_id":      c.tg_id,
            "balance":    c.balance,
            "created_at": c.created_at,
            "kids_count": len(c.kids),
            "kids": [
                {"id": k.id, "name": k.name, "gender": k.gender, "birth_date": k.birth_date}
                for k in c.kids
            ],
        }
        for c in customers
    ]


def get_all_transactions_admin(
    db: Session,
    page: int = 1,
    per_page: int = 25,
    search: str | None = None,
    tx_type: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    export: bool = False,
) -> dict:
    from datetime import timedelta

    query = db.query(Transaction).outerjoin(
        Customer, Transaction.customer_id == Customer.id
    )

    if search:
        query = query.filter(
            Customer.full_name.ilike(f"%{search}%") |
            Customer.phone.ilike(f"%{search}%")
        )
    if tx_type:
        query = query.filter(Transaction.type == tx_type)
    if date_from:
        try:
            dt_from = datetime.strptime(date_from, "%Y-%m-%d")
            query = query.filter(Transaction.created_at >= dt_from)
        except ValueError:
            pass
    if date_to:
        try:
            dt_to = datetime.strptime(date_to, "%Y-%m-%d") + timedelta(days=1)
            query = query.filter(Transaction.created_at < dt_to)
        except ValueError:
            pass

    total = query.count()
    base_query = query.order_by(Transaction.created_at.desc())

    if export:
        txs = base_query.all()
    else:
        txs = base_query.offset((page - 1) * per_page).limit(per_page).all()

    items = [
        {
            "id":             tx.id,
            "amount":         tx.amount,
            "type":           tx.type,
            "created_at":     tx.created_at,
            "expires_at":     tx.expires_at,
            "customer_name":  tx.customer.full_name if tx.customer else None,
            "customer_phone": tx.customer.phone     if tx.customer else None,
            "cashier_name":   tx.cashier.name       if tx.cashier  else None,
        }
        for tx in txs
    ]

    total_pages = max(1, (total + per_page - 1) // per_page) if not export else 1

    return {
        "items":       items,
        "total":       total,
        "page":        page,
        "per_page":    per_page,
        "total_pages": total_pages,
    }


# --- МАССОВОЕ НАЧИСЛЕНИЕ ---

def accrue_bonus_bulk(db: Session, customer_ids: list[int], amount: int) -> list[Customer]:
    """Начисляет бонусы списку клиентов, создаёт транзакцию для каждого."""
    expire_overdue_bonuses(db)
    expires_at = compute_expires_at(db) if amount > 0 else None
    customers = db.query(Customer).filter(Customer.id.in_(customer_ids)).all()
    for c in customers:
        c.balance += amount
        db.add(Transaction(
            customer_id=c.id,
            cashier_id=None,
            amount=amount,
            type=TransactionType.manual,
            expires_at=expires_at,
        ))
    db.commit()
    for c in customers:
        db.refresh(c)
    return customers

# 4. Провести транзакцию (Изменить баланс)
def process_transaction(db: Session, trans: schemas.TransactionCreate):
    expire_overdue_bonuses(db)
    customer = get_customer_by_phone(db, trans.customer_phone)
    if not customer:
        return None

    # Защита от отрицательного баланса при списании
    if trans.amount < 0 and customer.balance + trans.amount < 0:
        return "insufficient_balance"

    customer.balance += trans.amount

    db_transaction = Transaction(
        customer_id=customer.id,
        cashier_id=trans.cashier_id,
        amount=trans.amount,
        type=TransactionType.manual,
        expires_at=compute_expires_at(db) if trans.amount > 0 else None,
    )
    db.add(db_transaction)
    db.commit()
    db.refresh(customer)
    return customer


# ══════════════════════════════════════════════
# БРОНИРОВАНИЯ
# ══════════════════════════════════════════════

def check_time_conflict(
    db: Session,
    booking_date: date,
    time_start: str,
    time_end: str,
    exclude_id: int | None = None
) -> "Booking | None":
    """
    Проверяет конфликт с существующими бронями на ту же дату.
    Отменённые брони (status=cancelled) НЕ блокируют слот.
    Возвращает конфликтующую бронь или None.

    Алгоритм пересечения интервалов:
        Конфликт есть, если: existing.time_start < new.time_end
                              И existing.time_end > new.time_start
    Примеры:
        Существующая 12:00–14:00:
        - Новая 13:00–15:00 → КОНФЛИКТ
        - Новая 14:00–16:00 → нет конфликта (граница не считается)
        - Новая 10:00–12:00 → нет конфликта (граница не считается)
    """
    query = db.query(Booking).filter(
        Booking.date == booking_date,
        Booking.status != BookingStatus.cancelled,
        Booking.time_start < time_end,
        Booking.time_end > time_start,
    )
    if exclude_id is not None:
        query = query.filter(Booking.id != exclude_id)
    return query.first()


def create_booking(db: Session, data: schemas.BookingCreate) -> Booking:
    """
    Создаёт новое бронирование.
    Raises ValueError если есть конфликт времени.
    """
    conflict = check_time_conflict(db, data.date, data.time_start, data.time_end)
    if conflict:
        raise ValueError("Это время уже занято")

    booking = Booking(
        date=data.date,
        time_start=data.time_start,
        time_end=data.time_end,
        phone=data.phone,
        children_count=data.children_count,
        package=data.package,
        hero=data.hero,
        parent_name=data.parent_name,
        child_name=data.child_name,
        child_age=data.child_age,
        status=data.status,
        notes=data.notes,
    )
    db.add(booking)
    db.commit()
    db.refresh(booking)
    return booking


def get_bookings_by_month(db: Session, year: int, month: int) -> list[Booking]:
    """Возвращает все брони за указанный месяц, сортировка по дате + time_start."""
    from calendar import monthrange
    last_day = monthrange(year, month)[1]
    date_from = date(year, month, 1)
    date_to   = date(year, month, last_day)

    return (
        db.query(Booking)
        .filter(Booking.date >= date_from, Booking.date <= date_to)
        .order_by(Booking.date, Booking.time_start)
        .all()
    )


def get_booking_by_id(db: Session, booking_id: int) -> Booking | None:
    return db.query(Booking).filter(Booking.id == booking_id).first()


def update_booking(db: Session, booking_id: int, data: schemas.BookingUpdate) -> Booking | None:
    """
    Обновляет поля брони. Если меняются дата или время — проверяет конфликт.
    Все поля опциональны — обновляются только переданные (не None).
    """
    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        return None

    update_data = data.model_dump(exclude_none=True)

    # Если меняется дата или время — проверяем конфликт
    new_date  = update_data.get("date",       booking.date)
    new_start = update_data.get("time_start", booking.time_start)
    new_end   = update_data.get("time_end",   booking.time_end)

    if "date" in update_data or "time_start" in update_data or "time_end" in update_data:
        conflict = check_time_conflict(db, new_date, new_start, new_end, exclude_id=booking_id)
        if conflict:
            raise ValueError("Это время уже занято")

    for field, value in update_data.items():
        setattr(booking, field, value)

    booking.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(booking)
    return booking


def update_booking_status(db: Session, booking_id: int, status: BookingStatus) -> Booking | None:
    """Меняет только статус брони. Все переходы разрешены."""
    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        return None
    booking.status = status
    booking.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(booking)
    return booking


def delete_booking(db: Session, booking_id: int) -> bool:
    """
    Мягкое удаление: меняет статус на 'cancelled'.
    Запись физически не удаляется из БД (сохраняется история).
    Возвращает True если запись найдена, False если нет.
    """
    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        return False
    booking.status = BookingStatus.cancelled
    booking.updated_at = datetime.utcnow()
    db.commit()
    return True


def get_bookings_stats(db: Session) -> dict:
    """Статистика бронирований для дашборда."""
    from calendar import monthrange
    today = date.today()
    first_day_of_month = date(today.year, today.month, 1)
    last_day_of_month  = date(today.year, today.month, monthrange(today.year, today.month)[1])

    today_count = db.query(Booking).filter(
        Booking.date == today
    ).count()

    month_count = db.query(Booking).filter(
        Booking.date >= first_day_of_month,
        Booking.date <= last_day_of_month
    ).count()

    confirmed_count = db.query(Booking).filter(
        Booking.status == BookingStatus.confirmed,
        Booking.date >= today
    ).count()

    return {
        "bookings_today":      today_count,
        "bookings_this_month": month_count,
        "bookings_confirmed":  confirmed_count,
    }

