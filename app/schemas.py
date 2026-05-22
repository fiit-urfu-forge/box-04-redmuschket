"""Pydantic-схемы запросов и ответов API.

Точные тексты ошибок валидации (раздел 03 spec_kit.md) формируются вручную
в слое `crud`/роутеров, поэтому входные схемы намеренно «мягкие» (str),
а строгая бизнес-валидация выполняется отдельно.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# --- Company ---------------------------------------------------------------
class CompanyCreate(BaseModel):
    name: str = ""
    email: str = ""
    password: Optional[str] = None


class CompanyUpdate(BaseModel):
    # extra="forbid" → передача неизвестного/неизменяемого поля даёт ошибку,
    # которую обработчик превращает в 400 "Поле 'X' не поддерживается".
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = None
    email: Optional[str] = None


class CompanyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: str
    is_active: bool
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None


# --- Certificate -----------------------------------------------------------
class CertificateUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recipient_name: Optional[str] = None
    certificate_number: Optional[str] = None
    issue_date: Optional[date] = None


class CertificateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    company_id: int
    recipient_name: str
    certificate_number: str
    issue_date: date
    hash_sha256: str
    status: str
    created_at: datetime
    updated_at: datetime


# --- VerificationRequest ---------------------------------------------------
class VerificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: str
    hash_sha256: str
    matched_certificate_id: Optional[int] = None
    similarity_score: Optional[float] = None
    verified_at: Optional[datetime] = None
    created_at: datetime


class VerificationResult(BaseModel):
    """Расширенный ответ POST /verify — с данными о найденном владельце."""

    request: VerificationOut
    matched: bool
    message: str
    matched_company_name: Optional[str] = None
    matched_certificate_number: Optional[str] = None
    similarity_score: Optional[float] = None
    alert_id: Optional[int] = None


# --- Alert -----------------------------------------------------------------
class AlertOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    company_id: int
    certificate_id: int
    verification_request_id: int
    delivery_method: str
    delivery_status: str
    message_text: str
    retry_count: int
    sent_at: Optional[datetime] = None
    created_at: datetime


# --- AdminNotification -----------------------------------------------------
class AdminNotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    type: str
    severity: str
    message: str
    related_entity_id: Optional[int] = None
    is_resolved: bool
    created_at: datetime
    resolved_at: Optional[datetime] = None
    resolution_note: Optional[str] = None


class NotificationResolve(BaseModel):
    resolution_note: str = Field(default="", max_length=2000)


# --- Служебные -------------------------------------------------------------
class ModelStatus(BaseModel):
    ready: bool
    certificates_indexed: int
    similarity_threshold: float
    max_features: int
    message: str


class MessageResponse(BaseModel):
    detail: str
