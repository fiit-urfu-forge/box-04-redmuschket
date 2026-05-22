"""SQLAlchemy ORM-модели.

Сущности соответствуют разделу [01] spec_kit.md:
Company, Certificate, VerificationRequest, Alert, Admin, AdminNotification.

Статусы хранятся строками с CHECK-ограничением — это переносимо между
PostgreSQL и SQLite и не требует отдельных ENUM-типов БД.
"""
from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.database import Base


# --- Перечисления значений статусов ---------------------------------------
class CertificateStatus(str, enum.Enum):
    active = "active"
    revoked = "revoked"
    damaged = "damaged"


class VerificationStatus(str, enum.Enum):
    pending = "pending"
    completed = "completed"
    no_match = "no_match"
    corrupted = "corrupted"
    timeout = "timeout"


class DeliveryMethod(str, enum.Enum):
    email = "email"
    telegram = "telegram"


class DeliveryStatus(str, enum.Enum):
    pending = "pending"
    sent = "sent"
    failed = "failed"


class AdminRole(str, enum.Enum):
    super_admin = "super_admin"
    support = "support"


class Severity(str, enum.Enum):
    warning = "WARNING"
    error = "ERROR"
    critical = "CRITICAL"


def _values(enum_cls) -> list[str]:
    return [m.value for m in enum_cls]


def _in_check(column: str, enum_cls) -> str:
    options = ", ".join(f"'{v}'" for v in _values(enum_cls))
    return f"{column} IN ({options})"


# --- Сущности --------------------------------------------------------------
class Company(Base):
    """Организация, выдающая сертификаты."""

    __tablename__ = "companies"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    email = Column(String(320), nullable=False, unique=True)
    password_hash = Column(String(255), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    deleted_at = Column(DateTime, nullable=True)

    certificates = relationship(
        "Certificate", back_populates="company", cascade="all, delete-orphan"
    )
    alerts = relationship(
        "Alert", back_populates="company", cascade="all, delete-orphan"
    )


class Certificate(Base):
    """Выданный сертификат — запись о легитимном документе."""

    __tablename__ = "certificates"
    __table_args__ = (
        UniqueConstraint(
            "company_id", "certificate_number", name="uq_cert_company_number"
        ),
        CheckConstraint(
            _in_check("status", CertificateStatus), name="ck_certificate_status"
        ),
    )

    id = Column(Integer, primary_key=True)
    company_id = Column(
        Integer, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    recipient_name = Column(String(255), nullable=False, default="Unknown")
    certificate_number = Column(String(36), nullable=False)
    issue_date = Column(Date, nullable=False)
    pdf_path = Column(String(512), nullable=False)
    hash_sha256 = Column(String(64), nullable=False)
    # Разреженный TF-IDF вектор: {"indices": [...], "values": [...], "size": N}.
    # Плотные массивы запрещены spec_kit.md.
    tfidf_vector = Column(JSON, nullable=True)
    status = Column(String(16), nullable=False, default=CertificateStatus.active.value)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    company = relationship("Company", back_populates="certificates")
    verification_requests = relationship(
        "VerificationRequest", back_populates="matched_certificate"
    )
    alerts = relationship(
        "Alert", back_populates="certificate", cascade="all, delete-orphan"
    )


class VerificationRequest(Base):
    """Запрос на проверку подозрительного документа."""

    __tablename__ = "verification_requests"
    __table_args__ = (
        CheckConstraint(
            _in_check("status", VerificationStatus), name="ck_verification_status"
        ),
    )

    id = Column(Integer, primary_key=True)
    suspicious_file_path = Column(String(512), nullable=False)
    hash_sha256 = Column(String(64), nullable=False)
    matched_certificate_id = Column(
        Integer, ForeignKey("certificates.id", ondelete="SET NULL"), nullable=True
    )
    similarity_score = Column(Float, nullable=True)
    status = Column(
        String(16), nullable=False, default=VerificationStatus.pending.value
    )
    verified_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    archived = Column(Boolean, nullable=False, default=False)

    matched_certificate = relationship(
        "Certificate", back_populates="verification_requests"
    )
    alert = relationship(
        "Alert", back_populates="verification_request", uselist=False
    )


class Alert(Base):
    """Уведомление компании об обнаруженной подделке."""

    __tablename__ = "alerts"
    __table_args__ = (
        CheckConstraint(
            _in_check("delivery_method", DeliveryMethod), name="ck_alert_method"
        ),
        CheckConstraint(
            _in_check("delivery_status", DeliveryStatus), name="ck_alert_status"
        ),
    )

    id = Column(Integer, primary_key=True)
    company_id = Column(
        Integer, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    certificate_id = Column(
        Integer, ForeignKey("certificates.id", ondelete="CASCADE"), nullable=False
    )
    # Один запрос проверки порождает максимум одно уведомление (связь 1:1).
    verification_request_id = Column(
        Integer,
        ForeignKey("verification_requests.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    delivery_method = Column(
        String(16), nullable=False, default=DeliveryMethod.email.value
    )
    delivery_status = Column(
        String(16), nullable=False, default=DeliveryStatus.pending.value
    )
    message_text = Column(Text, nullable=False)
    retry_count = Column(Integer, nullable=False, default=0)
    sent_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    archived = Column(Boolean, nullable=False, default=False)

    company = relationship("Company", back_populates="alerts")
    certificate = relationship("Certificate", back_populates="alerts")
    verification_request = relationship(
        "VerificationRequest", back_populates="alert"
    )


class Admin(Base):
    """Администратор системы."""

    __tablename__ = "admins"
    __table_args__ = (
        CheckConstraint(_in_check("role", AdminRole), name="ck_admin_role"),
    )

    id = Column(Integer, primary_key=True)
    email = Column(String(320), nullable=False, unique=True)
    name = Column(String(255), nullable=False)
    role = Column(String(16), nullable=False, default=AdminRole.support.value)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    notifications = relationship("AdminNotification", back_populates="admin")


class AdminNotification(Base):
    """Системное уведомление для администратора (повреждённые данные и т.п.)."""

    __tablename__ = "admin_notifications"
    __table_args__ = (
        CheckConstraint(
            _in_check("severity", Severity), name="ck_admin_notification_severity"
        ),
    )

    id = Column(Integer, primary_key=True)
    admin_id = Column(
        Integer, ForeignKey("admins.id", ondelete="SET NULL"), nullable=True
    )
    type = Column(String(64), nullable=False)
    severity = Column(String(16), nullable=False, default=Severity.error.value)
    message = Column(Text, nullable=False)
    related_entity_id = Column(Integer, nullable=True)
    is_resolved = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    resolved_at = Column(DateTime, nullable=True)
    resolution_note = Column(Text, nullable=True)

    admin = relationship("Admin", back_populates="notifications")
