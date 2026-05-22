"""Работа с PDF: валидация, извлечение текста, хеширование, атомарное сохранение.

Коды ответов соответствуют разделам 02–03 и «Критериям готовности» spec_kit.md:
  * пустой файл (0 байт)        -> 400 «Файл пуст»
  * не PDF (нет сигнатуры)      -> 400 «не является корректным PDF»
  * размер > 10 МБ             -> 413
  * битый PDF / ошибка разбора -> 422
  * нет извлекаемого текста    -> 422
"""
from __future__ import annotations

import hashlib
import io
import os
import shutil
import uuid

import pdfplumber
from fastapi import HTTPException, status

from app.config import get_settings
from app.logging_config import logger

settings = get_settings()

PDF_SIGNATURE = b"%PDF"


def compute_sha256(data: bytes) -> str:
    """SHA-256 содержимого файла — используется для точной крипто-проверки."""
    return hashlib.sha256(data).hexdigest()


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def check_free_space(path: str) -> None:
    """Перед записью убеждаемся, что на диске есть место (раздел 03)."""
    ensure_dir(path)
    try:
        free = shutil.disk_usage(path).free
    except OSError as exc:  # pragma: no cover - зависит от ОС
        logger.error("Не удалось проверить свободное место в %s: %s", path, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Не удалось обработать файл, повторите попытку",
        )
    if free < settings.min_free_space_bytes:
        logger.error("Недостаточно места на диске для %s (свободно %d байт)", path, free)
        raise HTTPException(
            status_code=status.HTTP_507_INSUFFICIENT_STORAGE,
            detail="Недостаточно места на диске для сохранения файла",
        )


def validate_pdf_bytes(data: bytes) -> None:
    """Проверяет размер и сигнатуру файла. Текст не извлекает."""
    if len(data) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Файл пуст"
        )
    if len(data) > settings.max_pdf_size_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Файл слишком большой (макс. {settings.max_pdf_size_mb} МБ)",
        )
    if not data.startswith(PDF_SIGNATURE):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Загруженный файл не является корректным PDF",
        )


def extract_text(data: bytes) -> str:
    """Извлекает текст из PDF.

    Битый PDF        -> 422.
    PDF без текста   -> 422.
    Слишком длинный текст обрезается до MAX_TEXT_BYTES.
    """
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            pages_text = []
            for page in pdf.pages:
                page_text = page.extract_text() or ""
                pages_text.append(page_text)
        text = "\n".join(pages_text).strip()
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Не удалось разобрать PDF: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Загруженный файл повреждён и не может быть прочитан",
        )

    if not text:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="PDF не содержит текста. Используйте текстовую версию документа.",
        )

    encoded = text.encode("utf-8")
    if len(encoded) > settings.max_text_bytes:
        logger.info("Текст PDF обрезан до %d байт", settings.max_text_bytes)
        text = encoded[: settings.max_text_bytes].decode("utf-8", errors="ignore")
    return text


def save_pdf_atomic(data: bytes, dest_dir: str, prefix: str) -> str:
    """Атомарно сохраняет PDF: запись во временный файл + os.replace.

    При сбое в момент записи «висячий» файл не остаётся (раздел 02, п. 9
    «Критериев готовности»).
    """
    check_free_space(dest_dir)
    final_name = f"{prefix}_{uuid.uuid4().hex}.pdf"
    final_path = os.path.join(dest_dir, final_name)
    tmp_path = final_path + ".tmp"
    try:
        with open(tmp_path, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, final_path)
    except OSError as exc:
        logger.error("Ошибка записи PDF в %s: %s", final_path, exc)
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Не удалось сохранить файл, повторите попытку",
        )
    return final_path


def read_pdf_text_from_path(path: str) -> str:
    """Читает PDF с диска и извлекает текст (для переобучения модели).

    Используется при retrain. Поднимает FileNotFoundError / HTTPException,
    которые вызывающий код обрабатывает (помечает сертификат damaged).
    """
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    with open(path, "rb") as fh:
        data = fh.read()
    return extract_text(data)


def delete_file_quietly(path: str | None) -> None:
    """Удаляет файл, не падая при ошибке (для повреждённых suspicious-PDF)."""
    if not path:
        return
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError as exc:  # pragma: no cover
        logger.warning("Не удалось удалить файл %s: %s", path, exc)
