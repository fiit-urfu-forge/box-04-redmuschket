"""Общая настройка автотестов.

ВАЖНО: переменные окружения задаются ДО импорта приложения, чтобы оно
использовало изолированную SQLite-базу и временные каталоги хранилища.
"""
import os
import tempfile

# --- Изолированное окружение (до импорта app.*) ----------------------------
_TMP = tempfile.mkdtemp(prefix="certguard_test_")
os.environ["DATABASE_URL"] = "sqlite+pysqlite:///" + os.path.join(_TMP, "test.sqlite3")
os.environ["STORAGE_DIR"] = _TMP
os.environ["CERTIFICATES_DIR"] = os.path.join(_TMP, "certificates")
os.environ["SUSPICIOUS_DIR"] = os.path.join(_TMP, "suspicious")
os.environ["ARCHIVE_DIR"] = os.path.join(_TMP, "archive")
os.environ["MODELS_DIR"] = os.path.join(_TMP, "models")
os.environ["LOGS_DIR"] = os.path.join(_TMP, "logs")
os.environ["SMTP_HOST"] = ""  # режим симуляции email
os.environ["SIMILARITY_THRESHOLD"] = "0.7"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.ml import model_store  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_state():
    """Перед каждым тестом: чистая БД и сброшенная модель."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    model_store.vectorizer = None
    model_store.nn = None
    model_store.cert_ids = []
    model_store.degraded = False
    for path in (model_store.tfidf_path, model_store.nn_path):
        if os.path.exists(path):
            os.remove(path)

    yield

    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client():
    """HTTP-клиент с поднятым жизненным циклом приложения."""
    with TestClient(app) as test_client:
        yield test_client
