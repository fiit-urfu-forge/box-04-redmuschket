"""Тесты CRUD-операций над компаниями и валидации (разделы 02–03 spec_kit)."""
from tests.helpers import create_company


def test_create_company_ok(client):
    response = client.post(
        "/companies", json={"name": "ООО Ромашка", "email": "info@romashka.ru"}
    )
    assert response.status_code == 201
    body = response.json()
    assert body["id"] > 0
    assert body["is_active"] is True


def test_list_companies_empty(client):
    response = client.get("/companies")
    assert response.status_code == 200
    assert response.json() == []


def test_create_company_empty_name(client):
    response = client.post("/companies", json={"name": "", "email": "a@b.ru"})
    assert response.status_code == 400
    assert "обязательно" in response.json()["detail"]


def test_create_company_bad_email(client):
    response = client.post(
        "/companies", json={"name": "Тест", "email": "company@"}
    )
    assert response.status_code == 400
    assert "email" in response.json()["detail"].lower()


def test_create_company_empty_email(client):
    response = client.post("/companies", json={"name": "Тест", "email": ""})
    assert response.status_code == 400


def test_create_company_duplicate_email(client):
    create_company(client, email="dup@example.com")
    response = client.post(
        "/companies", json={"name": "Другая", "email": "dup@example.com"}
    )
    assert response.status_code == 409


def test_create_company_long_name(client):
    response = client.post(
        "/companies", json={"name": "x" * 300, "email": "long@example.com"}
    )
    assert response.status_code == 400
    assert "255" in response.json()["detail"]


def test_get_company_not_found(client):
    response = client.get("/companies/999")
    assert response.status_code == 404


def test_update_company_ok(client):
    company = create_company(client)
    response = client.put(
        f"/companies/{company['id']}", json={"name": "Новое название"}
    )
    assert response.status_code == 200
    assert response.json()["name"] == "Новое название"


def test_update_company_forbidden_field(client):
    company = create_company(client)
    response = client.put(
        f"/companies/{company['id']}", json={"created_at": "2020-01-01"}
    )
    assert response.status_code == 400
    assert "created_at" in response.json()["detail"]


def test_deactivate_and_reactivate_company(client):
    company = create_company(client)
    cid = company["id"]

    deleted = client.delete(f"/companies/{cid}")
    assert deleted.status_code == 200
    assert deleted.json()["is_active"] is False

    reactivated = client.post(f"/companies/{cid}/reactivate")
    assert reactivated.status_code == 200
    assert reactivated.json()["is_active"] is True
