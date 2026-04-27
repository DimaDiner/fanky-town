from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# Абсолютный путь: иначе при разном cwd у API и бота получались две разные БД.
_BASE_DIR = Path(__file__).resolve().parent.parent
_DB_PATH = _BASE_DIR / "funky_bonus.db"
SQLALCHEMY_DATABASE_URL = f"sqlite:///{_DB_PATH.as_posix()}"

# Подключаемся (check_same_thread нужен только для SQLite)
engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)

# Создаем фабрику сессий (через них мы будем делать запросы)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Базовый класс для наших таблиц
Base = declarative_base()

# Вспомогательная функция для получения сессии БД
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()