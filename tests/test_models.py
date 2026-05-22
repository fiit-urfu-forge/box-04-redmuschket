"""Тесты обучения / переобучения модели TF-IDF."""
from tests.helpers import ORIGINAL_TEXT, create_company, issue_certificate


def test_retrain_without_data_returns_400(client):
    """Граничный случай №8: retrain без сертификатов -> 400."""
    response = client.post("/models/retrain")
    assert response.status_code == 400
    assert "Нет данных" in response.json()["detail"]


def test_model_status_initially_not_ready(client):
    response = client.get("/models/status")
    assert response.status_code == 200
    body = response.json()
    assert body["ready"] is False
    assert body["max_features"] == 5000
    assert body["similarity_threshold"] == 0.7


def test_retrain_after_issuing_certificate(client):
    company = create_company(client)
    issue_certificate(client, company["id"], text=ORIGINAL_TEXT)

    response = client.post("/models/retrain")
    assert response.status_code == 200
    assert "1" in response.json()["detail"]

    status = client.get("/models/status").json()
    assert status["ready"] is True
    assert status["certificates_indexed"] == 1


def test_model_becomes_ready_after_issue(client):
    """Выпуск сертификата автоматически обучает модель."""
    company = create_company(client)
    issue_certificate(client, company["id"], text=ORIGINAL_TEXT)
    status = client.get("/models/status").json()
    assert status["ready"] is True
