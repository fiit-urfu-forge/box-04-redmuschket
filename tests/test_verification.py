"""Тесты проверки подозрительных документов (поиск подделок)."""
from tests.helpers import (
    DIFFERENT_TEXT,
    ORIGINAL_TEXT,
    create_company,
    issue_certificate,
    make_pdf,
)


def _verify(client, pdf_bytes, filename="suspect.pdf"):
    return client.post(
        "/verify",
        files={"file": (filename, pdf_bytes, "application/pdf")},
    )


def test_verify_no_certificates_returns_no_match(client):
    """Граничный случай №6: в базе 0 сертификатов -> no_match без ошибок."""
    response = _verify(client, make_pdf(ORIGINAL_TEXT))
    assert response.status_code == 200
    body = response.json()
    assert body["matched"] is False
    assert body["request"]["status"] == "no_match"
    assert body["alert_id"] is None


def test_verify_match_creates_alert(client):
    """Основной сценарий: загружен PDF, совпадающий с оригиналом."""
    company = create_company(client)
    issue_certificate(client, company["id"], text=ORIGINAL_TEXT)

    response = _verify(client, make_pdf(ORIGINAL_TEXT))
    assert response.status_code == 200
    body = response.json()
    assert body["matched"] is True
    assert body["request"]["status"] == "completed"
    assert body["similarity_score"] >= 0.7
    assert body["alert_id"] is not None

    alerts = client.get("/alerts").json()
    assert len(alerts) == 1
    assert alerts[0]["company_id"] == company["id"]


def test_verify_no_match(client):
    """Документ не похож ни на один сертификат -> no_match, Alert не создаётся."""
    company = create_company(client)
    issue_certificate(client, company["id"], text=ORIGINAL_TEXT)

    response = _verify(client, make_pdf(DIFFERENT_TEXT))
    assert response.status_code == 200
    body = response.json()
    assert body["matched"] is False
    assert body["request"]["status"] == "no_match"
    assert body["alert_id"] is None
    assert client.get("/alerts").json() == []


def test_verify_corrupt_pdf(client):
    response = _verify(client, b"%PDF-1.4 totally broken file")
    assert response.status_code == 422


def test_verify_empty_file(client):
    response = _verify(client, b"")
    assert response.status_code == 400


def test_verify_duplicate_request(client):
    """Граничный случай №5: тот же файл проверяется дважды -> 409."""
    company = create_company(client)
    issue_certificate(client, company["id"], text=ORIGINAL_TEXT)

    pdf = make_pdf(DIFFERENT_TEXT)
    first = _verify(client, pdf)
    assert first.status_code == 200
    second = _verify(client, pdf)
    assert second.status_code == 409


def test_revoked_certificate_excluded_from_search(client):
    """Отозванный сертификат не участвует в поиске ближайших соседей."""
    company = create_company(client)
    cert = issue_certificate(client, company["id"], text=ORIGINAL_TEXT).json()
    client.post(f"/certificates/{cert['id']}/revoke")

    response = _verify(client, make_pdf(ORIGINAL_TEXT))
    assert response.status_code == 200
    assert response.json()["matched"] is False
