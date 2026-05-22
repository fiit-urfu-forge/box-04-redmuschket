"""Бизнес-логика и операции с БД.

Здесь сосредоточены все правила валидации и точные тексты ошибок
(разделы 02–03 spec_kit.md). Роутеры остаются «тонкими».
"""
from __future__ import annotations

import re
from datetime import date, datetime

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.config import get_settings
from app.logging_config import logger
from app.ml import model_store
from app.models import (
    AdminNotification,
    Alert,
    Certificate,
    CertificateStatus,
    Company,
    DeliveryMethod,
    DeliveryStatus,
    VerificationRequest,
    VerificationStatus,
)
from app.pdf_utils import (
    compute_sha256,
    delete_file_quietly,
    extract_text,
    save_pdf_atomic,
    validate_pdf_bytes,
)

settings = get_settings()

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Поля, которые нельзя изменять через PUT.
_COMPANY_UPDATABLE = {"name", "email"}
_CERTIFICATE_UPDATABLE = {"recipient_name", "certificate_number", "issue_date"}
_CERTIFICATE_ADMIN_ONLY = {"pdf_path", "hash_sha256"}


# --- Валидация полей -------------------------------------------------------
def _validate_company_name(name) -> str:
    if name is None or str(name).strip() == "":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Название компании обязательно")
    name = str(name).strip()
    if len(name) > 255:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Название не должно превышать 255 символов"
        )
    return name


def _validate_company_email(email) -> str:
    if email is None or str(email).strip() == "":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Email обязателен для уведомлений"
        )
    email = str(email).strip()
    if len(email) > 320:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Email не должен превышать 320 символов"
        )
    if not _EMAIL_RE.match(email):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Укажите корректный email адрес"
        )
    return email


def _parse_issue_date(value) -> date:
    if isinstance(value, date):
        parsed = value
    else:
        if value is None or str(value).strip() == "":
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "Дата выдачи обязательна"
            )
        try:
            parsed = date.fromisoformat(str(value).strip())
        except ValueError:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Дата должна быть в формате YYYY-MM-DD",
            )
    if parsed > date.today():
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Дата выдачи не может быть позже текущей даты",
        )
    return parsed


# ===========================================================================
#  Company
# ===========================================================================
def create_company(db: Session, name, email, password: str | None = None) -> Company:
    name = _validate_company_name(name)
    email = _validate_company_email(email)

    if db.query(Company).filter(Company.email == email).first():
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Компания с таким email уже зарегистрирована",
        )

    company = Company(name=name, email=email, password_hash=password, is_active=True)
    db.add(company)
    db.commit()
    db.refresh(company)
    logger.info("Создана компания id=%s (%s)", company.id, company.email)
    return company


def get_company(db: Session, company_id: int) -> Company:
    company = db.get(Company, company_id)
    if company is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"Компания с id={company_id} не найдена"
        )
    return company


def list_companies(db: Session) -> list[Company]:
    return db.query(Company).order_by(Company.id).all()


def update_company(db: Session, company_id: int, payload: dict) -> Company:
    company = get_company(db, company_id)

    unknown = set(payload) - _COMPANY_UPDATABLE
    if unknown:
        field = sorted(unknown)[0]
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"Поле '{field}' не поддерживается"
        )

    if "name" in payload:
        company.name = _validate_company_name(payload["name"])
    if "email" in payload:
        new_email = _validate_company_email(payload["email"])
        if new_email != company.email and (
            db.query(Company).filter(Company.email == new_email).first()
        ):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Компания с таким email уже зарегистрирована",
            )
        company.email = new_email

    db.commit()
    db.refresh(company)
    return company


def deactivate_company(db: Session, company_id: int) -> Company:
    """Логическое удаление компании: is_active=False (раздел 01 spec_kit).

    Сертификаты физически НЕ удаляются (запрет раздела «Что НЕ надо делать»).
    """
    company = get_company(db, company_id)
    if company.is_active:
        company.is_active = False
        company.deleted_at = datetime.utcnow()
        db.commit()
        db.refresh(company)
        logger.info("Компания id=%s деактивирована", company_id)
    return company


def reactivate_company(db: Session, company_id: int) -> Company:
    company = get_company(db, company_id)
    if not company.is_active:
        company.is_active = True
        company.deleted_at = None
        db.commit()
        db.refresh(company)
        logger.info("Компания id=%s реактивирована", company_id)
    return company


# ===========================================================================
#  Certificate
# ===========================================================================
def get_certificate(db: Session, certificate_id: int) -> Certificate:
    cert = db.get(Certificate, certificate_id)
    if cert is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"Сертификат с id={certificate_id} не найден",
        )
    return cert


def list_certificates(db: Session, company_id: int | None = None) -> list[Certificate]:
    query = db.query(Certificate)
    if company_id is not None:
        query = query.filter(Certificate.company_id == company_id)
    return query.order_by(Certificate.id).all()


def issue_certificate(
    db: Session,
    company_id: int,
    recipient_name: str | None,
    certificate_number: str | None,
    issue_date,
    file_bytes: bytes,
) -> Certificate:
    """Выпуск сертификата: валидация PDF, хеш, текст, TF-IDF, переобучение."""
    # --- компания ----------------------------------------------------------
    company = db.get(Company, company_id)
    if company is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"Компания с id={company_id} не найдена (или неактивна)",
        )
    if not company.is_active:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Компания заблокирована, выпуск сертификатов невозможен",
        )

    # --- recipient_name ----------------------------------------------------
    if recipient_name is None:
        recipient_name = "Unknown"
    else:
        recipient_name = str(recipient_name).strip()
        if recipient_name == "":
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "Имя получателя не может быть пустым"
            )
        if len(recipient_name) > 255:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Имя получателя не должно превышать 255 символов",
            )

    # --- certificate_number ------------------------------------------------
    if certificate_number is None or str(certificate_number).strip() == "":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Номер сертификата обязателен"
        )
    certificate_number = str(certificate_number).strip()
    if len(certificate_number) > 36:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Номер сертификата не должен превышать 36 символов",
        )

    # --- дата --------------------------------------------------------------
    parsed_date = _parse_issue_date(issue_date)

    # --- уникальность номера в рамках компании -----------------------------
    duplicate = (
        db.query(Certificate)
        .filter(
            Certificate.company_id == company_id,
            Certificate.certificate_number == certificate_number,
        )
        .first()
    )
    if duplicate:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Сертификат с номером '{certificate_number}' уже существует для этой компании",
        )

    # --- PDF ---------------------------------------------------------------
    validate_pdf_bytes(file_bytes)         # 400 / 413
    extract_text(file_bytes)               # 422 — проверяем читаемость и наличие текста
    file_hash = compute_sha256(file_bytes)
    pdf_path = save_pdf_atomic(file_bytes, settings.certificates_dir, "cert")

    cert = Certificate(
        company_id=company_id,
        recipient_name=recipient_name,
        certificate_number=certificate_number,
        issue_date=parsed_date,
        pdf_path=pdf_path,
        hash_sha256=file_hash,
        status=CertificateStatus.active.value,
    )
    db.add(cert)
    db.flush()  # получаем cert.id, файл уже на диске

    # Переобучаем модель — TF-IDF векторы пересчитываются и сохраняются.
    try:
        model_store.rebuild(db)  # внутри делает commit
    except Exception as exc:  # pragma: no cover - защитный блок
        db.rollback()
        delete_file_quietly(pdf_path)
        logger.error("Ошибка переобучения модели при выпуске сертификата: %s", exc)
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "Не удалось обработать сертификат, повторите попытку",
        )

    db.refresh(cert)
    logger.info("Выпущен сертификат id=%s (компания %s)", cert.id, company_id)
    return cert


def update_certificate(db: Session, certificate_id: int, payload: dict) -> Certificate:
    cert = get_certificate(db, certificate_id)

    # Попытка изменить поля, доступные только администратору.
    admin_only = set(payload) & _CERTIFICATE_ADMIN_ONLY
    if admin_only:
        field = sorted(admin_only)[0]
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"Поле '{field}' может изменять только администратор",
        )

    unknown = set(payload) - _CERTIFICATE_UPDATABLE
    if unknown:
        field = sorted(unknown)[0]
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"Поле '{field}' не поддерживается"
        )

    # Если сертификат уже участвовал в проверках — менять идентифицирующие
    # поля нельзя, это «стёрло бы» историю (раздел 03 spec_kit).
    has_history = (
        db.query(VerificationRequest)
        .filter(VerificationRequest.matched_certificate_id == certificate_id)
        .first()
        is not None
    )
    identity_change = "certificate_number" in payload or "recipient_name" in payload
    if has_history and identity_change:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Нельзя изменить данные сертификата, так как он уже использовался "
            "в проверках. Создайте новый сертификат и при необходимости отзовите этот.",
        )

    if "recipient_name" in payload:
        value = str(payload["recipient_name"]).strip()
        if value == "":
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "Имя получателя не может быть пустым"
            )
        cert.recipient_name = value

    if "certificate_number" in payload:
        new_number = str(payload["certificate_number"]).strip()
        if new_number == "":
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "Номер сертификата обязателен"
            )
        if new_number != cert.certificate_number:
            clash = (
                db.query(Certificate)
                .filter(
                    Certificate.company_id == cert.company_id,
                    Certificate.certificate_number == new_number,
                )
                .first()
            )
            if clash:
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    f"Сертификат с номером '{new_number}' уже существует для этой компании",
                )
            cert.certificate_number = new_number

    if "issue_date" in payload:
        cert.issue_date = _parse_issue_date(payload["issue_date"])

    db.commit()
    db.refresh(cert)
    return cert


def revoke_certificate(db: Session, certificate_id: int) -> Certificate:
    """Отзыв сертификата. Повторный отзыв -> 409."""
    cert = get_certificate(db, certificate_id)
    if cert.status == CertificateStatus.revoked.value:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Сертификат уже отозван"
        )
    cert.status = CertificateStatus.revoked.value
    db.flush()
    # Отозванный сертификат исключается из поиска ближайших соседей.
    model_store.rebuild(db)
    db.refresh(cert)
    logger.info("Сертификат id=%s отозван", certificate_id)
    return cert


def logical_delete_certificate(db: Session, certificate_id: int) -> Certificate:
    """DELETE /certificates/{id} — логическое удаление.

    Физическое удаление записей Certificate запрещено spec_kit.md, поэтому
    DELETE выполняет отзыв (идемпотентно: повторный вызов не ошибка).
    """
    cert = get_certificate(db, certificate_id)
    if cert.status == CertificateStatus.active.value:
        cert.status = CertificateStatus.revoked.value
        db.flush()
        model_store.rebuild(db)
        db.refresh(cert)
        logger.info("Сертификат id=%s логически удалён (revoked)", certificate_id)
    return cert


# ===========================================================================
#  VerificationRequest / verify
# ===========================================================================
def _count_searchable_certificates(db: Session) -> int:
    return (
        db.query(Certificate)
        .join(Company, Certificate.company_id == Company.id)
        .filter(Certificate.status == CertificateStatus.active.value)
        .filter(Company.is_active.is_(True))
        .count()
    )


def _build_alert_message(cert: Certificate, vr: VerificationRequest, similarity: float) -> str:
    return (
        f"Обнаружена возможная подделка вашего сертификата.\n"
        f"Номер сертификата: {cert.certificate_number}\n"
        f"Получатель: {cert.recipient_name}\n"
        f"Степень сходства: {similarity:.0%}\n"
        f"Идентификатор проверки: #{vr.id}\n"
        f"Дата проверки: {datetime.utcnow():%Y-%m-%d %H:%M} UTC"
    )


def verify_document(db: Session, file_bytes: bytes) -> dict:
    """Проверка подозрительного PDF.

    Возвращает словарь с результатом. Поле `alert_id` (если задано) сигналит
    роутеру о необходимости запустить фоновую отправку уведомления.
    """
    # 1. Валидация файла — до создания VerificationRequest (раздел 03).
    validate_pdf_bytes(file_bytes)      # 400 / 413
    text = extract_text(file_bytes)     # 422

    file_hash = compute_sha256(file_bytes)

    # 2. Тот же файл уже проверялся — конфликт (граничный случай №5).
    existing = (
        db.query(VerificationRequest)
        .filter(
            VerificationRequest.hash_sha256 == file_hash,
            VerificationRequest.status.in_(
                [VerificationStatus.completed.value, VerificationStatus.no_match.value]
            ),
        )
        .order_by(VerificationRequest.id.desc())
        .first()
    )
    if existing:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Этот файл уже проверялся (запрос #{existing.id}, статус '{existing.status}')",
        )

    # 3. Доступность модели. Если активных сертификатов нет — это не ошибка
    #    (no_match). Если они есть, а модель не готова — файлы моделей утеряны.
    searchable = _count_searchable_certificates(db)
    model_ready = model_store.is_ready()
    if not model_ready and searchable > 0:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Система проверки временно недоступна, идёт восстановление",
        )

    # 4. Сохраняем подозрительный файл и создаём запрос.
    suspicious_path = save_pdf_atomic(file_bytes, settings.suspicious_dir, "suspicious")
    vr = VerificationRequest(
        suspicious_file_path=suspicious_path,
        hash_sha256=file_hash,
        status=VerificationStatus.pending.value,
    )
    db.add(vr)
    db.flush()

    # 5. В базе нет сертификатов -> no_match без ошибок и без Alert.
    if not model_ready or searchable == 0:
        vr.status = VerificationStatus.no_match.value
        vr.verified_at = datetime.utcnow()
        db.commit()
        db.refresh(vr)
        return {
            "request": vr,
            "matched": False,
            "message": "Совпадений не найдено",
            "matched_company_name": None,
            "matched_certificate_number": None,
            "similarity_score": None,
            "alert_id": None,
        }

    # 6. Поиск ближайшего сертификата.
    matched_cert_id, similarity = model_store.query(text)

    if matched_cert_id is None or similarity < settings.similarity_threshold:
        vr.status = VerificationStatus.no_match.value
        vr.matched_certificate_id = None
        vr.similarity_score = float(similarity)
        vr.verified_at = datetime.utcnow()
        db.commit()
        db.refresh(vr)
        logger.info("Проверка #%s: совпадений нет (similarity=%.3f)", vr.id, similarity)
        return {
            "request": vr,
            "matched": False,
            "message": "Совпадений не найдено",
            "matched_company_name": None,
            "matched_certificate_number": None,
            "similarity_score": float(similarity),
            "alert_id": None,
        }

    # 7. Подделка найдена: completed + Alert.
    cert = db.get(Certificate, matched_cert_id)
    company = db.get(Company, cert.company_id)
    vr.status = VerificationStatus.completed.value
    vr.matched_certificate_id = cert.id
    vr.similarity_score = float(similarity)
    vr.verified_at = datetime.utcnow()
    db.flush()

    alert = Alert(
        company_id=cert.company_id,
        certificate_id=cert.id,
        verification_request_id=vr.id,
        delivery_method=DeliveryMethod.email.value,
        delivery_status=DeliveryStatus.pending.value,
        message_text=_build_alert_message(cert, vr, similarity),
    )
    db.add(alert)
    db.commit()
    db.refresh(vr)
    db.refresh(alert)
    logger.info(
        "Проверка #%s: найдена подделка сертификата id=%s (similarity=%.3f)",
        vr.id, cert.id, similarity,
    )
    return {
        "request": vr,
        "matched": True,
        "message": "Подделка найдена, уведомление будет отправлено владельцу",
        "matched_company_name": company.name if company else None,
        "matched_certificate_number": cert.certificate_number,
        "similarity_score": float(similarity),
        "alert_id": alert.id,
    }


def get_verification(db: Session, request_id: int) -> VerificationRequest:
    vr = db.get(VerificationRequest, request_id)
    if vr is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"Запрос проверки с id={request_id} не найден"
        )
    return vr


def list_verifications(db: Session) -> list[VerificationRequest]:
    return (
        db.query(VerificationRequest)
        .order_by(VerificationRequest.id.desc())
        .all()
    )


# ===========================================================================
#  Alert / AdminNotification
# ===========================================================================
def list_alerts(db: Session, company_id: int | None = None) -> list[Alert]:
    query = db.query(Alert)
    if company_id is not None:
        query = query.filter(Alert.company_id == company_id)
    return query.order_by(Alert.id.desc()).all()


def list_admin_notifications(
    db: Session, only_unresolved: bool = False
) -> list[AdminNotification]:
    query = db.query(AdminNotification)
    if only_unresolved:
        query = query.filter(AdminNotification.is_resolved.is_(False))
    return query.order_by(AdminNotification.id.desc()).all()


def resolve_admin_notification(
    db: Session, notification_id: int, note: str
) -> AdminNotification:
    notification = db.get(AdminNotification, notification_id)
    if notification is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"Уведомление с id={notification_id} не найдено",
        )
    notification.is_resolved = True
    notification.resolved_at = datetime.utcnow()
    notification.resolution_note = note or ""
    db.commit()
    db.refresh(notification)
    return notification


def retrain_models(db: Session) -> int:
    """Ручное переобучение моделей. При отсутствии сертификатов -> 400."""
    count = model_store.rebuild(db)
    if count == 0:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Нет данных для обучения"
        )
    return count
