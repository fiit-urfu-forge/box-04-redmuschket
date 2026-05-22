"""Подключение к базе данных и фабрика сессий.

Используется connection pooling с таймаутами (требование раздела 03 spec_kit).
Поддерживаются PostgreSQL (боевой режим) и SQLite (автотесты).
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import get_settings

settings = get_settings()

_connect_args: dict = {}
_engine_kwargs: dict = {"pool_pre_ping": True}

if settings.database_url.startswith("sqlite"):
    # SQLite — только для автотестов.
    _connect_args = {"check_same_thread": False}
else:
    # PostgreSQL — пул соединений с таймаутом.
    _engine_kwargs.update(
        pool_size=10,
        max_overflow=10,
        pool_timeout=settings.db_timeout_seconds,
        connect_args={"connect_timeout": settings.db_timeout_seconds},
    )

if _connect_args:
    _engine_kwargs["connect_args"] = _connect_args

engine = create_engine(settings.database_url, **_engine_kwargs)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


def get_db():
    """FastAPI-зависимость: выдаёт сессию и гарантированно закрывает её."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
