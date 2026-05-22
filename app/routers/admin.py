"""Административные эндпоинты: модель, уведомления, alerts."""
from fastapi import APIRouter, Depends
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from app import crud
from app.config import get_settings
from app.database import get_db
from app.ml import model_store
from app.schemas import (
    AdminNotificationOut,
    AlertOut,
    MessageResponse,
    ModelStatus,
    NotificationResolve,
)

router = APIRouter(tags=["admin"])
settings = get_settings()


@router.post("/models/retrain", response_model=MessageResponse)
async def retrain_models(db: Session = Depends(get_db)):
    """Ручное переобучение TF-IDF и NearestNeighbors с нуля."""
    count = await run_in_threadpool(crud.retrain_models, db)
    return MessageResponse(
        detail=f"Модель переобучена на {count} активных сертификатах"
    )


@router.get("/models/status", response_model=ModelStatus)
def model_status():
    """Текущее состояние модели проверки."""
    ready = model_store.is_ready()
    if ready:
        message = "Модель готова к проверкам"
    elif model_store.degraded:
        message = "Файлы моделей повреждены — требуется переобучение (retrain)"
    else:
        message = "Модель не обучена — выпустите сертификаты или запустите retrain"
    return ModelStatus(
        ready=ready,
        certificates_indexed=len(model_store.cert_ids),
        similarity_threshold=settings.similarity_threshold,
        max_features=settings.tfidf_max_features,
        message=message,
    )


@router.get("/alerts", response_model=list[AlertOut], tags=["admin"])
def list_alerts(company_id: int | None = None, db: Session = Depends(get_db)):
    """Список отправленных уведомлений (опционально — по компании)."""
    return crud.list_alerts(db, company_id)


@router.get(
    "/admin/notifications",
    response_model=list[AdminNotificationOut],
    tags=["admin"],
)
def list_admin_notifications(
    only_unresolved: bool = False, db: Session = Depends(get_db)
):
    """Системные уведомления для администраторов."""
    return crud.list_admin_notifications(db, only_unresolved)


@router.post(
    "/admin/notifications/{notification_id}/resolve",
    response_model=AdminNotificationOut,
    tags=["admin"],
)
def resolve_notification(
    notification_id: int,
    payload: NotificationResolve,
    db: Session = Depends(get_db),
):
    """Пометить системное уведомление как обработанное."""
    return crud.resolve_admin_notification(
        db, notification_id, payload.resolution_note
    )
