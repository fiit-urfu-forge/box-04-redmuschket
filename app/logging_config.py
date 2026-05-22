"""Настройка логирования: вывод в stdout (Docker) и в файл ./logs/app.log."""
import logging
import os
from logging.handlers import RotatingFileHandler

from app.config import get_settings

_configured = False


def setup_logging() -> logging.Logger:
    global _configured
    settings = get_settings()
    logger = logging.getLogger("certguard")

    if _configured:
        return logger

    logger.setLevel(logging.INFO)
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    stream = logging.StreamHandler()
    stream.setFormatter(fmt)
    logger.addHandler(stream)

    try:
        os.makedirs(settings.logs_dir, exist_ok=True)
        file_handler = RotatingFileHandler(
            os.path.join(settings.logs_dir, "app.log"),
            maxBytes=5 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setFormatter(fmt)
        logger.addHandler(file_handler)
    except OSError:
        # Файловая система недоступна — продолжаем писать только в stdout.
        logger.warning("Не удалось открыть файл логов, логирование только в stdout")

    _configured = True
    return logger


logger = setup_logging()
