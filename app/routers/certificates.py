"""Эндпоинты выпуска, чтения, обновления и отзыва сертификатов."""
import os

from fastapi import (
    APIRouter,
    Body,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app import crud
from app.database import get_db
from app.logging_config import logger
from app.models import AdminNotification, CertificateStatus, Severity
from app.schemas import CertificateOut

router = APIRouter(prefix="/certificates", tags=["certificates"])


@router.post("", response_model=CertificateOut, status_code=status.HTTP_201_CREATED)
async def issue_certificate(
    company_id: int = Form(...),
    certificate_number: str = Form(...),
    issue_date: str = Form(..., description="Дата выдачи в формате YYYY-MM-DD"),
    recipient_name: str | None = Form(default=None),
    file: UploadFile = File(..., description="Оригинальный PDF сертификата"),
    db: Session = Depends(get_db),
):
    """Выпуск сертификата: загрузка оригинального PDF."""
    file_bytes = await file.read()
    cert = await run_in_threadpool(
        crud.issue_certificate,
        db,
        company_id,
        recipient_name,
        certificate_number,
        issue_date,
        file_bytes,
    )
    return cert


@router.get("", response_model=list[CertificateOut])
def list_certificates(company_id: int | None = None, db: Session = Depends(get_db)):
    """Список сертификатов (опционально — по компании)."""
    return crud.list_certificates(db, company_id)


@router.get("/{certificate_id}", response_model=CertificateOut)
def get_certificate(certificate_id: int, db: Session = Depends(get_db)):
    return crud.get_certificate(db, certificate_id)


@router.get("/{certificate_id}/download")
def download_certificate(certificate_id: int, db: Session = Depends(get_db)):
    """Скачивание оригинального PDF (точная проверка по хешу)."""
    cert = crud.get_certificate(db, certificate_id)
    if not os.path.exists(cert.pdf_path):
        # Файл существует в БД, но отсутствует на диске — повреждение хранилища.
        logger.error("Certificate %s: PDF file corrupted or missing", certificate_id)
        if cert.status != CertificateStatus.damaged.value:
            cert.status = CertificateStatus.damaged.value
            db.add(
                AdminNotification(
                    type="corrupted_certificate",
                    severity=Severity.critical.value,
                    message=f"PDF сертификата id={certificate_id} отсутствует на диске",
                    related_entity_id=certificate_id,
                )
            )
            db.commit()
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "Файл сертификата повреждён, обратитесь к администратору",
        )
    return FileResponse(
        cert.pdf_path,
        media_type="application/pdf",
        filename=f"certificate_{cert.certificate_number}.pdf",
        headers={"X-Certificate-SHA256": cert.hash_sha256},
    )


@router.put("/{certificate_id}", response_model=CertificateOut)
def update_certificate(
    certificate_id: int,
    payload: dict = Body(
        ..., description="Изменяемые поля: recipient_name, certificate_number, issue_date"
    ),
    db: Session = Depends(get_db),
):
    """Обновление сертификата (с учётом ограничений раздела 03 spec_kit)."""
    return crud.update_certificate(db, certificate_id, payload)


@router.post("/{certificate_id}/revoke", response_model=CertificateOut)
def revoke_certificate(certificate_id: int, db: Session = Depends(get_db)):
    """Отзыв сертификата — исключает его из поиска ближайших соседей."""
    return crud.revoke_certificate(db, certificate_id)


@router.delete("/{certificate_id}", response_model=CertificateOut)
def delete_certificate(certificate_id: int, db: Session = Depends(get_db)):
    """Логическое удаление сертификата (физическое удаление запрещено spec_kit)."""
    return crud.logical_delete_certificate(db, certificate_id)
