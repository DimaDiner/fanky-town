from sqlalchemy import Column, Integer, BigInteger, String, DateTime, Date, ForeignKey, Enum, Boolean, Text
from sqlalchemy.orm import relationship
from datetime import datetime
import enum
from .database import Base

# --- Перечисления ---
class StaffRole(str, enum.Enum):
    cashier  = "cashier"   # Кассир (кассовый терминал Telegram)
    admin    = "admin"     # Администратор (полный доступ к CRM)
    operator = "operator"  # Оператор (только просмотр бронирований в CRM)
    booker   = "booker"    # Кассир CRM (полный доступ к вкладке «Бронирования»)

class TransactionType(str, enum.Enum):
    manual       = "manual"        # Кассир списал/начислил на кассе
    registration = "registration"  # Авто-бонус за регистрацию
    birthday     = "birthday"      # Авто-бонус на ДР
    expiry       = "expiry"        # Сторно просроченных бонусов

class BookingStatus(str, enum.Enum):
    draft     = "draft"      # Черновик
    confirmed = "confirmed"  # Подтверждён
    cancelled = "cancelled"  # Отменён

class HeroType(str, enum.Enum):
    labubu    = "labubu"     # Лабубу
    stitch    = "stitch"     # Стич
    zootopia  = "zootopia"   # Зверополис
    batman    = "batman"     # Бэтмен
    superman  = "superman"   # Супермен
    ironman   = "ironman"    # Железный человек
    unicorn   = "unicorn"    # Единорожка
    deadpool  = "deadpool"   # Дедпул
    huntix    = "huntix"     # Хантрикс
    spongebob = "spongebob"  # Спанч Боб и Патрик
    sonic     = "sonic"      # Соник
    fury_cat  = "fury_cat"   # Фури Кот
    spiderman = "spiderman"  # Человек-паук
    lol_doll  = "lol_doll"   # Кукла LOL

class PackageType(str, enum.Enum):
    lite          = "lite"           # Фанки Лайт
    vip           = "vip"            # Фанки Вип
    extreme       = "extreme"        # Фанки Экстрим
    all_inclusive = "all_inclusive"  # Фанки Все включено

# ==========================================
# ТАБЛИЦА 1: ПЕРСОНАЛ (Кассиры и Админы)
# ==========================================
class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=True)  # Логин для входа в CRM
    password_hash = Column(String, nullable=True)                      # Хеш пароля (только CRM)
    tg_id = Column(BigInteger, unique=True, index=True, nullable=True)
    tg_username = Column(String, nullable=True)       # @username без символа @
    invite_token = Column(String, unique=True, nullable=True, index=True)  # одноразовый токен приглашения
    role = Column(Enum(StaffRole), nullable=False)
    name = Column(String, nullable=False)
    is_active = Column(Boolean, default=False)        # False до подтверждения через бота
    created_at = Column(DateTime, default=datetime.utcnow)

    processed_transactions = relationship("Transaction", back_populates="cashier")

# ==========================================
# ТАБЛИЦА 2: КЛИЕНТЫ
# ==========================================
class Customer(Base):
    __tablename__ = "customers"

    id = Column(Integer, primary_key=True, index=True)
    tg_id = Column(BigInteger, unique=True, index=True) # ID клиента в Telegram
    phone = Column(String, unique=True, index=True, nullable=True)
    full_name = Column(String, nullable=True)
    balance = Column(Integer, default=0) # Баланс бонусов
    created_at = Column(DateTime, default=datetime.utcnow)

    # Связи
    kids = relationship("Kid", back_populates="parent")
    transactions = relationship("Transaction", back_populates="customer")

# ==========================================
# ТАБЛИЦА 3: ДЕТИ КЛИЕНТОВ
# ==========================================
class Kid(Base):
    __tablename__ = "kids"

    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id")) # Привязка к ID клиента
    name = Column(String)
    gender = Column(String) # 'boy' или 'girl'
    birth_date = Column(Date) # Только дата, без времени

    parent = relationship("Customer", back_populates="kids")

# ==========================================
# ТАБЛИЦА 4: ТРАНЗАКЦИИ
# ==========================================
class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id")) # Кому начислили/списали
    cashier_id = Column(Integer, ForeignKey("users.id"), nullable=True) # Кто провел (пусто, если авто-бонус)
    amount = Column(Integer) # Сумма: +500 (начисление) или -500 (списание)
    type = Column(Enum(TransactionType), default=TransactionType.manual)
    expires_at = Column(DateTime, nullable=True, index=True)  # Срок жизни партии начисления
    created_at = Column(DateTime, default=datetime.utcnow)

    customer = relationship("Customer", back_populates="transactions")
    cashier = relationship("User", back_populates="processed_transactions")

# ==========================================
# ТАБЛИЦА 5: НАСТРОЙКИ СИСТЕМЫ
# ==========================================
class Setting(Base):
    __tablename__ = "settings"

    key   = Column(String, primary_key=True, index=True)
    value = Column(Text, nullable=False)

# ==========================================
# ТАБЛИЦА 6: БРОНИРОВАНИЯ
# ==========================================
class Booking(Base):
    __tablename__ = "bookings"

    id             = Column(Integer, primary_key=True, index=True)
    date           = Column(Date, nullable=False, index=True)
    time_start     = Column(String(5), nullable=False)   # "HH:MM"
    time_end       = Column(String(5), nullable=False)   # "HH:MM"
    phone          = Column(String, nullable=False)
    children_count = Column(Integer, nullable=False)
    package        = Column(Enum(PackageType), nullable=False)
    hero           = Column(Enum(HeroType), nullable=False)
    parent_name    = Column(String, nullable=False)
    child_name     = Column(String, nullable=False)
    child_age      = Column(Integer, nullable=False)
    status         = Column(Enum(BookingStatus), nullable=False, default=BookingStatus.draft)
    notes          = Column(Text, nullable=True)
    created_at     = Column(DateTime, default=datetime.utcnow)
    updated_at     = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)