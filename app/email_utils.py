"""Асинхронная отправка email-уведомлений (Alert).

Отправка выполняется фоновой задачей FastAPI и НЕ влияет на ответ пользователю
(раздел 03 spec_kit.md). При сбое — повторные попытки с экспоненциальной
задержкой; после исчерпания попыток Alert остаётся в статусе 'failed' и
администратор получает системное уведомление.

Если SMTP_HOST не задан — режим симуляции: письмо логируется, статус 'sent'.
"""
from __future__ import annotations

import smtplib
import time
from datetime import datetime
from email.message import EmailMessage

from app.config import get_settings
from app.database import SessionLocal
from app.logging_config import logger
from app.models import AdminNotification, Alert, Company, DeliveryStatus, Severity

settings = get_settings()


def _smtp_send(to_addr: str, subject: str, body: str) -> None:
    """Одна попытка отправки письма. Бросает исключение при ошибке."""
    msg = EmailMessage()
    msg["From"] = settings.smtp_from
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg.set_content(body)

    with smtplib.SMTP(
        settings.smtp_host, settings.smtp_port, timeout=settings.smtp_timeout_seconds
    ) as server:
        server.ehlo()
        if server.has_extn("STARTTLS"):
            server.starttls()
            server.ehlo()
        if settings.smtp_user:
            server.login(settings.smtp_user, settings.smtp_password)
        server.send_message(msg)


def send_alert_email(alert_id: int) -> None:
    """Фоновая задача: доставляет уведомление и обновляет его статус."""
    db = SessionLocal()
    try:
        alert = db.get(Alert, alert_id)
        if alert is None:
            logger.warning("Alert id=%s не найден для отправки", alert_id)
            return
        company = db.get(Company, alert.company_id)
        if company is None:
            logger.warning("Компания для Alert id=%s не найдена", alert_id)
            return

        subject = "CertGuard: обнаружена возможная подделка вашего сертификата"

        # Режим симуляции — SMTP не настроен.
        if not settings.smtp_host:
            logger.info(
                "[SIMULATED EMAIL] -> %s | %s\n%s",
                company.email, subject, alert.message_text,
            )
            alert.delivery_status = DeliveryStatus.sent.value
            alert.sent_at = datetime.utcnow()
            db.commit()
            return

        # Реальная отправка с повторными попытками.
        for attempt in range(1, settings.email_max_retries + 1):
            alert.retry_count = attempt
            try:
                _smtp_send(company.email, subject, alert.message_text)
                alert.delivery_status = DeliveryStatus.sent.value
                alert.sent_at = datetime.utcnow()
                db.commit()
                logger.info("Уведомление Alert id=%s доставлено на %s", alert_id, company.email)
                return
            except Exception as exc:
                logger.warning(
                    "Попытка %d/%d отправки Alert id=%s не удалась: %s",
                    attempt, settings.email_max_retries, alert_id, exc,
                )
                db.commit()
                if attempt < settings.email_max_retries:
                    time.sleep(min(2 ** (attempt - 1), 8))  # экспоненциальная задержка

        # Все попытки исчерпаны.
        alert.delivery_status = DeliveryStatus.failed.value
        db.add(
            AdminNotification(
                type="email_delivery_failed",
                severity=Severity.error.value,
                message=(
                    f"Не удалось доставить уведомление Alert id={alert_id} "
                    f"на адрес {company.email} после {settings.email_max_retries} попыток"
                ),
                related_entity_id=alert_id,
            )
        )
        db.commit()
        logger.error("Alert id=%s переведён в статус failed", alert_id)
    except Exception as exc:  # pragma: no cover - защитный блок фоновой задачи
        logger.error("Ошибка фоновой задачи отправки Alert id=%s: %s", alert_id, exc)
        db.rollback()
    finally:
        db.close()
