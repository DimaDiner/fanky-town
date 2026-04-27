from pydantic import BaseModel
from typing import Optional, List
from datetime import date, datetime
from db.models import StaffRole, TransactionType

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