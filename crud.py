from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, date
from db.models import Customer, Kid, Transaction, TransactionType, User, Setting
import schemas
from config import REGISTRATION_BONUS

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

def get_all_settings(db: Session) -> dict:
    rows = db.query(Setting).all()
    result = {"registration_bonus": str(REGISTRATION_BONUS)}
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
            type=TransactionType.registration
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

    return {
        "total_customers":     total_customers,
        "active_cashiers":     active_cashiers,
        "bonuses_issued_today": int(issued_today),
        "bonuses_spent_today":  abs(int(spent_today)),
        "total_bonus_balance":  int(total_balance),
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
    customers = db.query(Customer).filter(Customer.id.in_(customer_ids)).all()
    for c in customers:
        c.balance += amount
        db.add(Transaction(
            customer_id=c.id,
            cashier_id=None,
            amount=amount,
            type=TransactionType.manual
        ))
    db.commit()
    for c in customers:
        db.refresh(c)
    return customers

# 4. Провести транзакцию (Изменить баланс)
def process_transaction(db: Session, trans: schemas.TransactionCreate):
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
        type=TransactionType.manual
    )
    db.add(db_transaction)
    db.commit()
    db.refresh(customer)
    return customer

