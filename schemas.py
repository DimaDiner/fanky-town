from pydantic import BaseModel, validator
from typing import Optional, List
from datetime import date, datetime

# Алиас: поле `date` в BookingUpdate иначе затеняет тип date в Optional[date]
DateType = date
from db.models import StaffRole, TransactionType, BookingStatus, HeroType, PackageType

# --- Схемы для ДЕТЕЙ ---
class KidBase(BaseModel):
    name: str
    gender: str
    birth_date: date

class KidCreate(KidBase):
    pass

class KidResponse(KidBase):
    id: int
    class Config:
        from_attributes = True # Разрешаем читать данные из ORM-моделей

# --- Схемы для КЛИЕНТОВ ---
class CustomerBase(BaseModel):
    phone: str
    full_name: Optional[str] = None
    tg_id: Optional[int] = None

class CustomerCreate(CustomerBase):
    kids: List[KidCreate] = [] # При создании можно сразу передать список детей

class CustomerProfileUpdate(BaseModel):
    full_name: Optional[str] = None

class CustomerResponse(CustomerBase):
    id: int
    balance: int
    created_at: datetime
    kids: List[KidResponse] = []

    class Config:
        from_attributes = True

# --- Схемы для ПЕРСОНАЛА ---
class StaffCreate(BaseModel):
    name: str
    tg_username: str
    role: StaffRole = StaffRole.cashier

class StaffResponse(BaseModel):
    id: int
    name: str
    tg_username: Optional[str] = None
    tg_id: Optional[int] = None
    role: StaffRole
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True

class StaffInviteResponse(StaffResponse):
    invite_link: str

class StaffConfirm(BaseModel):
    tg_id: int
    tg_username: Optional[str] = None

# --- Схемы для ТРАНЗАКЦИЙ ---
class TransactionCreate(BaseModel):
    customer_phone: str
    amount: int
    cashier_id: Optional[int] = None

class TransactionResponse(BaseModel):
    id: int
    new_balance: int
    status: str

class TransactionHistoryItem(BaseModel):
    id: int
    amount: int
    type: TransactionType
    created_at: datetime

    class Config:
        from_attributes = True


# --- Схемы для АДМИНКИ ---
class AdminStats(BaseModel):
    total_customers: int
    active_cashiers: int
    bonuses_issued_today: int
    bonuses_spent_today: int
    total_bonus_balance: int


class AdminKidItem(BaseModel):
    id: int
    name: str
    gender: str
    birth_date: date

    class Config:
        from_attributes = True


class AdminCustomerItem(BaseModel):
    id: int
    full_name: Optional[str] = None
    phone: Optional[str] = None
    tg_id: Optional[int] = None
    balance: int
    created_at: datetime
    kids_count: int = 0
    kids: List[AdminKidItem] = []


class AdminTransactionItem(BaseModel):
    id: int
    amount: int
    type: TransactionType
    created_at: datetime
    customer_name: Optional[str] = None
    customer_phone: Optional[str] = None
    cashier_name: Optional[str] = None


class AdminTransactionPage(BaseModel):
    items: List[AdminTransactionItem]
    total: int
    page: int
    per_page: int
    total_pages: int


# --- Схемы для НАСТРОЕК ---
class SettingUpdate(BaseModel):
    value: str

class SettingResponse(BaseModel):
    key: str
    value: str

    class Config:
        from_attributes = True


# --- Схемы для МАССОВОГО НАЧИСЛЕНИЯ ---
class BonusAccrueRequest(BaseModel):
    customer_ids: List[int]
    amount: int

class BonusAccrueResponse(BaseModel):
    accrued_count: int
    total_amount: int


# --- Схемы для РАССЫЛКИ ---
class BroadcastResponse(BaseModel):
    sent_count: int
    failed_count: int
    no_tg_count: int
    total: int


# ══════════════════════════════════════════════
# СХЕМЫ ДЛЯ БРОНИРОВАНИЙ (День рождения)
# ══════════════════════════════════════════════

# Вспомогательная функция: парсинг времени "HH:MM" → (hours, minutes)
def _parse_time(t: str) -> tuple[int, int]:
    h, m = map(int, t.split(":"))
    return h, m


class BookingCreate(BaseModel):
    date: date
    time_start: str                              # Формат "HH:MM"
    time_end: str                                # Формат "HH:MM"
    phone: str
    children_count: int
    package: PackageType
    hero: HeroType
    parent_name: str
    child_name: str
    child_age: int
    status: BookingStatus = BookingStatus.draft
    notes: Optional[str] = None

    @validator("time_start", "time_end")
    def validate_time_format(cls, v):
        import re
        if not re.match(r"^\d{2}:\d{2}$", v):
            raise ValueError("Время должно быть в формате HH:MM")
        h, m = _parse_time(v)
        if not (0 <= h <= 23 and 0 <= m <= 59):
            raise ValueError("Некорректное время")
        if h < 10 or (h == 22 and m > 0) or h > 22:
            raise ValueError("Время доступно с 10:00 до 22:00")
        return v

    @validator("time_end")
    def validate_duration(cls, v, values):
        if "time_start" not in values:
            return v
        sh, sm = _parse_time(values["time_start"])
        eh, em = _parse_time(v)
        start_min = sh * 60 + sm
        end_min   = eh * 60 + em
        if end_min <= start_min:
            raise ValueError("Время окончания должно быть позже времени начала")
        if end_min - start_min < 30:
            raise ValueError("Минимальная длительность брони — 30 минут")
        return v

    @validator("children_count")
    def validate_children(cls, v):
        if v < 1:
            raise ValueError("Количество детей должно быть не менее 1")
        return v

    @validator("child_age")
    def validate_age(cls, v):
        if v < 0 or v > 18:
            raise ValueError("Возраст ребёнка должен быть от 0 до 18 лет")
        return v

    @validator("parent_name", "child_name")
    def validate_not_empty(cls, v):
        if not v or not v.strip():
            raise ValueError("Поле не может быть пустым")
        return v.strip()


class BookingUpdate(BaseModel):
    date: Optional[DateType] = None
    time_start: Optional[str] = None
    time_end: Optional[str] = None
    phone: Optional[str] = None
    children_count: Optional[int] = None
    package: Optional[PackageType] = None
    hero: Optional[HeroType] = None
    parent_name: Optional[str] = None
    child_name: Optional[str] = None
    child_age: Optional[int] = None
    status: Optional[BookingStatus] = None
    notes: Optional[str] = None


class BookingStatusUpdate(BaseModel):
    status: BookingStatus


class BookingResponse(BaseModel):
    id: int
    date: date
    time_start: str
    time_end: str
    phone: str
    children_count: int
    package: PackageType
    hero: HeroType
    parent_name: str
    child_name: str
    child_age: int
    status: BookingStatus
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class BookingListItem(BaseModel):
    """Краткое представление для отображения в календаре."""
    id: int
    date: date
    time_start: str
    time_end: str
    child_name: str
    parent_name: str
    phone: str
    status: BookingStatus
    package: PackageType
    hero: HeroType
    children_count: int

    class Config:
        from_attributes = True


class BookingConflictResponse(BaseModel):
    """Ответ на проверку конфликта времён."""
    conflict: bool
    conflicting_booking: Optional[BookingListItem] = None


# Расширение AdminStats для бронирований (используется в задаче 04)
class AdminStatsExtended(AdminStats):
    """Расширенная статистика с добавлением данных о бронированиях."""
    bookings_today: int = 0
    bookings_this_month: int = 0
    bookings_confirmed: int = 0


# ══════════════════════════════════════════════
# СХЕМЫ ДЛЯ АВТОРИЗАЦИИ CRM
# ══════════════════════════════════════════════

class CRMLoginRequest(BaseModel):
    username: str
    password: str


class CRMUserResponse(BaseModel):
    id: int
    name: str
    role: StaffRole

    class Config:
        from_attributes = True