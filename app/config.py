"""Конфигурация приложения.

Все настраиваемые параметры читаются из переменных окружения (или из .env).
Порог близости и max_features вынесены в конфиг — менять их в коде запрещено
требованиями spec_kit.md.
"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- База данных -------------------------------------------------------
    database_url: str = "postgresql+psycopg2://certguard:certguard@db:5432/certguard"
    db_timeout_seconds: int = 10

    # --- Хранилище файлов --------------------------------------------------
    storage_dir: str = "./storage"
    certificates_dir: str = "./storage/certificates"
    suspicious_dir: str = "./storage/suspicious"
    archive_dir: str = "./storage/archive"
    models_dir: str = "./models"
    logs_dir: str = "./logs"

    # --- Ограничения -------------------------------------------------------
    max_pdf_size_mb: int = 10
    min_free_space_mb: int = 15
    max_text_bytes: int = 3 * 1024 * 1024  # 3 МБ извлечённого текста

    # --- TF-IDF / поиск ----------------------------------------------------
    tfidf_max_features: int = 5000
    similarity_threshold: float = 0.7
    nn_neighbors: int = 1

    # --- Email / SMTP ------------------------------------------------------
    smtp_host: str = ""
    smtp_port: int = 25
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "no-reply@certguard.local"
    smtp_timeout_seconds: int = 10
    email_max_retries: int = 3

    # --- Архивация ---------------------------------------------------------
    archive_after_days: int = 5

    @property
    def max_pdf_size_bytes(self) -> int:
        return self.max_pdf_size_mb * 1024 * 1024

    @property
    def min_free_space_bytes(self) -> int:
        return self.min_free_space_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()
