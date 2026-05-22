"""Эндпоинты проверки подозрительных документов."""
from fastapi import APIRouter, BackgroundTasks, Depends, File, UploadFile
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from app import crud
from app.database import get_db
from app.email_utils import send_alert_email
from app.schemas import VerificationOut, VerificationResult

router = APIRouter(tags=["verification"])


@router.post("/verify", response_model=VerificationResult)
async def verify_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="Подозрительный PDF для проверки"),
    db: Session = Depends(get_db),
):
    """Проверка подозрительного PDF на сходство с выданными сертификатами."""
    file_bytes = await file.read()
    result = await run_in_threadpool(crud.verify_document, db, file_bytes)

    # Отправка уведомления — асинхронно, не влияет на ответ пользователю.
    if result["alert_id"] is not None:
        background_tasks.add_task(send_alert_email, result["alert_id"])

    return VerificationResult(
        request=VerificationOut.model_validate(result["request"]),
        matched=result["matched"],
        message=result["message"],
        matched_company_name=result["matched_company_name"],
        matched_certificate_number=result["matched_certificate_number"],
        similarity_score=result["similarity_score"],
        alert_id=result["alert_id"],
    )


@router.get("/verifications", response_model=list[VerificationOut], tags=["verification"])
def list_verifications(db: Session = Depends(get_db)):
    """История запросов на проверку (новые сверху)."""
    return crud.list_verifications(db)


@router.get(
    "/verifications/{request_id}",
    response_model=VerificationOut,
    tags=["verification"],
)
def get_verification(request_id: int, db: Session = Depends(get_db)):
    return crud.get_verification(db, request_id)
