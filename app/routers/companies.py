"""CRUD-эндпоинты для компаний."""
from fastapi import APIRouter, Body, Depends, status
from sqlalchemy.orm import Session

from app import crud
from app.database import get_db
from app.schemas import CompanyCreate, CompanyOut

router = APIRouter(prefix="/companies", tags=["companies"])


@router.post("", response_model=CompanyOut, status_code=status.HTTP_201_CREATED)
def create_company(payload: CompanyCreate, db: Session = Depends(get_db)):
    """Регистрация компании."""
    return crud.create_company(db, payload.name, payload.email, payload.password)


@router.get("", response_model=list[CompanyOut])
def list_companies(db: Session = Depends(get_db)):
    """Список всех компаний (пустой список, если их нет)."""
    return crud.list_companies(db)


@router.get("/{company_id}", response_model=CompanyOut)
def get_company(company_id: int, db: Session = Depends(get_db)):
    return crud.get_company(db, company_id)


@router.put("/{company_id}", response_model=CompanyOut)
def update_company(
    company_id: int,
    payload: dict = Body(..., description="Изменяемые поля: name, email"),
    db: Session = Depends(get_db),
):
    """Изменение названия / контактного email компании."""
    return crud.update_company(db, company_id, payload)


@router.delete("/{company_id}", response_model=CompanyOut)
def delete_company(company_id: int, db: Session = Depends(get_db)):
    """Логическое удаление: is_active=False. Сертификаты не удаляются."""
    return crud.deactivate_company(db, company_id)


@router.post("/{company_id}/reactivate", response_model=CompanyOut)
def reactivate_company(company_id: int, db: Session = Depends(get_db)):
    """Повторная активация ранее заблокированной компании."""
    return crud.reactivate_company(db, company_id)
