"""Точка входа FastAPI-приложения CertGuard."""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import InterfaceError, OperationalError
from sqlalchemy.exc import TimeoutError as SATimeoutError

from app import __version__
from app.config import get_settings
from app.logging_config import logger
from app.ml import model_store
from app.routers import admin, certificates, companies, verification, web

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Старт приложения: создаём каталоги и пробуем загрузить модели."""
    for path in (
        settings.storage_dir,
        settings.certificates_dir,
        settings.suspicious_dir,
        settings.archive_dir,
        settings.models_dir,
        settings.logs_dir,
    ):
        os.makedirs(path, exist_ok=True)

    # При старте всегда пробуем загрузить модель TF-IDF / NearestNeighbors.
    model_store.load()
    logger.info("CertGuard %s запущен (модель готова: %s)", __version__, model_store.is_ready())
    yield
    logger.info("CertGuard остановлен")


app = FastAPI(
    title="CertGuard",
    description="Система проверки подлинности сертификатов (TF-IDF поиск подделок)",
    version=__version__,
    lifespan=lifespan,
)

# Статические файлы (CSS, JS).
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# API-роутеры.
app.include_router(companies.router)
app.include_router(certificates.router)
app.include_router(verification.router)
app.include_router(admin.router)
# Веб-интерфейс.
app.include_router(web.router)


# --- Обработчики ошибок ----------------------------------------------------
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Ошибки валидации тела запроса -> 400 с понятным сообщением (раздел 03)."""
    errors = exc.errors()
    detail = "Некорректный запрос"
    if errors:
        first = errors[0]
        etype = first.get("type", "")
        loc = [str(p) for p in first.get("loc", []) if p not in ("body", "query")]
        field = loc[-1] if loc else "значение"
        if etype == "extra_forbidden":
            detail = f"Поле '{field}' не поддерживается"
        elif etype == "missing":
            if field == "file":
                detail = "Файл сертификата не приложен"
            else:
                detail = f"Обязательное поле '{field}' не передано"
        else:
            detail = f"Некорректное значение поля '{field}': {first.get('msg', '')}".strip()
    return JSONResponse(status_code=400, content={"detail": detail})


async def _db_unavailable_handler(request: Request, exc: Exception):
    """Отказ/таймаут БД -> 503 Service Unavailable (разделы 03)."""
    logger.critical("Database unavailable: %s", exc)
    return JSONResponse(
        status_code=503,
        content={"detail": "База данных временно недоступна, попробуйте позже"},
    )


app.add_exception_handler(OperationalError, _db_unavailable_handler)
app.add_exception_handler(InterfaceError, _db_unavailable_handler)
app.add_exception_handler(SATimeoutError, _db_unavailable_handler)


@app.get("/health", tags=["service"], include_in_schema=False)
def health():
    return {"status": "ok", "version": __version__, "model_ready": model_store.is_ready()}
