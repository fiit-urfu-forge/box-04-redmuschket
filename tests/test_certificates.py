"""Тесты выпуска, обновления, отзыва и скачивания сертификатов."""
from tests.helpers import (
    ORIGINAL_TEXT,
    create_company,
    issue_certificate,
    make_pdf,
)


def test_issue_certificate_ok(client):
    company = create_company(client)
    response = issue_certificate(client, company["id"])
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "active"
    assert len(body["hash_sha256"]) == 64


def test_issue_certificate_inactive_company(client):
    company = create_company(client)
    client.delete(f"/companies/{company['id']}")  # деактивация
    response = issue_certificate(client, company["id"])
    assert response.status_code == 403


def test_issue_certificate_unknown_company(client):
    response = issue_certificate(client, 999)
    assert response.status_code == 404


def test_issue_certificate_duplicate_number(client):
    company = create_company(client)
    issue_certificate(client, company["id"], number="ABC-123")
    response = issue_certificate(client, company["id"], number="ABC-123")
    assert response.status_code == 409


def test_issue_certificate_future_date(client):
    company = create_company(client)
    response = issue_certificate(client, company["id"], issue_date="2099-01-01")
    assert response.status_code == 400
    assert "будущ" in response.json()["detail"] or "позже" in response.json()["detail"]


def test_issue_certificate_bad_date_format(client):
    company = create_company(client)
    response = issue_certificate(client, company["id"], issue_date="01-01-2025")
    assert response.status_code == 400


def test_issue_certificate_empty_file(client):
    company = create_company(client)
    response = client.post(
        "/certificates",
        data={
            "company_id": company["id"],
            "certificate_number": "E-1",
            "issue_date": "2025-01-01",
        },
        files={"file": ("empty.pdf", b"", "application/pdf")},
    )
    assert response.status_code == 400
    assert "пуст" in response.json()["detail"]


def test_issue_certificate_not_pdf(client):
    company = create_company(client)
    response = client.post(
        "/certificates",
        data={
            "company_id": company["id"],
            "certificate_number": "NP-1",
            "issue_date": "2025-01-01",
        },
        files={"file": ("fake.pdf", b"just plain text", "application/pdf")},
    )
    assert response.status_code == 400


def test_issue_certificate_corrupt_pdf(client):
    company = create_company(client)
    response = client.post(
        "/certificates",
        data={
            "company_id": company["id"],
            "certificate_number": "C-1",
            "issue_date": "2025-01-01",
        },
        files={"file": ("broken.pdf", b"%PDF-1.4 broken garbage data", "application/pdf")},
    )
    assert response.status_code == 422


def test_revoke_certificate(client):
    company = create_company(client)
    cert = issue_certificate(client, company["id"]).json()

    revoked = client.post(f"/certificates/{cert['id']}/revoke")
    assert revoked.status_code == 200
    assert revoked.json()["status"] == "revoked"

    # Повторный отзыв -> 409.
    again = client.post(f"/certificates/{cert['id']}/revoke")
    assert again.status_code == 409


def test_download_certificate(client):
    company = create_company(client)
    cert = issue_certificate(client, company["id"]).json()
    response = client.get(f"/certificates/{cert['id']}/download")
    assert response.status_code == 200
    assert response.content.startswith(b"%PDF")
    assert response.headers["x-certificate-sha256"] == cert["hash_sha256"]


def test_update_certificate_admin_only_field(client):
    company = create_company(client)
    cert = issue_certificate(client, company["id"]).json()
    response = client.put(
        f"/certificates/{cert['id']}", json={"hash_sha256": "0" * 64}
    )
    assert response.status_code == 403


def test_update_certificate_recipient(client):
    company = create_company(client)
    cert = issue_certificate(client, company["id"]).json()
    response = client.put(
        f"/certificates/{cert['id']}", json={"recipient_name": "Пётр Сидоров"}
    )
    assert response.status_code == 200
    assert response.json()["recipient_name"] == "Пётр Сидоров"
