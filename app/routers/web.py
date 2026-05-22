"""Веб-интерфейс (Jinja2 + Bootstrap). Минимальный, на серверном рендеринге."""
from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app import crud
from app.config import get_settings
from app.database import get_db
from app.email_utils import send_alert_email
from app.ml import model_store

router = APIRouter(include_in_schema=False)
templates = Jinja2Templates(directory="app/templates")
settings = get_settings()


@router.get("/", response_class=HTMLResponse)
def index(request: Request, db: Session = Depends(get_db)):
    companies = crud.list_companies(db)
    certificates = crud.list_certificates(db)
    verifications = crud.list_verifications(db)
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "companies_count": len(companies),
            "certificates_count": len(certificates),
            "verifications_count": len(verifications),
            "model_ready": model_store.is_ready(),
            "model_indexed": len(model_store.cert_ids),
            "threshold": settings.similarity_threshold,
        },
    )


@router.get("/ui/companies", response_class=HTMLResponse)
def companies_page(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(
        "companies.html",
        {"request": request, "companies": crud.list_companies(db), "error": None,
         "message": request.query_params.get("message")},
    )


@router.post("/ui/companies", response_class=HTMLResponse)
def companies_create(
    request: Request,
    name: str = Form(""),
    email: str = Form(""),
    db: Session = Depends(get_db),
):
    error = None
    message = None
    try:
        company = crud.create_company(db, name, email)
        message = f"Компания «{company.name}» зарегистрирована (id={company.id})"
    except HTTPException as exc:
        error = exc.detail
    return templates.TemplateResponse(
        "companies.html",
        {"request": request, "companies": crud.list_companies(db),
         "error": error, "message": message},
    )


@router.post("/ui/companies/{company_id}/deactivate", response_class=HTMLResponse)
def companies_deactivate(
    request: Request, company_id: int, db: Session = Depends(get_db)
):
    error = None
    message = None
    try:
        crud.deactivate_company(db, company_id)
        message = f"Компания id={company_id} деактивирована"
    except HTTPException as exc:
        error = exc.detail
    return templates.TemplateResponse(
        "companies.html",
        {"request": request, "companies": crud.list_companies(db),
         "error": error, "message": message},
    )


@router.post("/ui/companies/{company_id}/reactivate", response_class=HTMLResponse)
def companies_reactivate(
    request: Request, company_id: int, db: Session = Depends(get_db)
):
    error = None
    message = None
    try:
        crud.reactivate_company(db, company_id)
        message = f"Компания id={company_id} реактивирована"
    except HTTPException as exc:
        error = exc.detail
    return templates.TemplateResponse(
        "companies.html",
        {"request": request, "companies": crud.list_companies(db),
         "error": error, "message": message},
    )


@router.get("/ui/certificates", response_class=HTMLResponse)
def certificates_page(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(
        "certificates.html",
        {
            "request": request,
            "companies": crud.list_companies(db),
            "certificates": crud.list_certificates(db),
            "error": None,
            "message": None,
        },
    )


@router.post("/ui/certificates", response_class=HTMLResponse)
async def certificates_create(
    request: Request,
    company_id: int = Form(...),
    certificate_number: str = Form(...),
    issue_date: str = Form(...),
    recipient_name: str = Form(""),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    error = None
    message = None
    file_bytes = await file.read()
    try:
        cert = await run_in_threadpool(
            crud.issue_certificate,
            db,
            company_id,
            recipient_name or None,
            certificate_number,
            issue_date,
            file_bytes,
        )
        message = f"Сертификат №{cert.certificate_number} выпущен (id={cert.id})"
    except HTTPException as exc:
        error = exc.detail
    return templates.TemplateResponse(
        "certificates.html",
        {
            "request": request,
            "companies": crud.list_companies(db),
            "certificates": crud.list_certificates(db),
            "error": error,
            "message": message,
        },
    )


@router.post("/ui/certificates/{certificate_id}/revoke", response_class=HTMLResponse)
def certificates_revoke(
    request: Request, certificate_id: int, db: Session = Depends(get_db)
):
    error = None
    message = None
    try:
        crud.revoke_certificate(db, certificate_id)
        message = f"Сертификат id={certificate_id} отозван"
    except HTTPException as exc:
        error = exc.detail
    return templates.TemplateResponse(
        "certificates.html",
        {
            "request": request,
            "companies": crud.list_companies(db),
            "certificates": crud.list_certificates(db),
            "error": error,
            "message": message,
        },
    )


@router.get("/ui/verify", response_class=HTMLResponse)
def verify_page(request: Request):
    return templates.TemplateResponse(
        "verify.html", {"request": request, "result": None, "error": None}
    )


@router.post("/ui/verify", response_class=HTMLResponse)
async def verify_submit(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    error = None
    result = None
    file_bytes = await file.read()
    try:
        result = await run_in_threadpool(crud.verify_document, db, file_bytes)
        if result["alert_id"] is not None:
            send_alert_email(result["alert_id"])
    except HTTPException as exc:
        error = exc.detail
    return templates.TemplateResponse(
        "verify.html", {"request": request, "result": result, "error": error}
    )


@router.get("/ui/verifications", response_class=HTMLResponse)
def verifications_page(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(
        "verifications.html",
        {"request": request, "verifications": crud.list_verifications(db)},
    )
