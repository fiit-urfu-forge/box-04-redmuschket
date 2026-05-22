"""Вспомогательные функции для тестов: генерация PDF и типовые запросы."""
from __future__ import annotations


def make_pdf(text: str) -> bytes:
    """Собирает минимальный валидный PDF с одной строкой текста.

    Не требует внешних библиотек — нужен только для автотестов, чтобы у PDF
    был извлекаемый pdfplumber'ом текст.
    """
    safe = text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
    content = (
        "BT /F1 18 Tf 72 700 Td (" + safe + ") Tj ET"
    ).encode("latin-1", "replace")

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n"
        + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]

    pdf = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf += f"{index} 0 obj\n".encode() + obj + b"\nendobj\n"

    xref_offset = len(pdf)
    size = len(objects) + 1
    pdf += f"xref\n0 {size}\n".encode()
    pdf += b"0000000000 65535 f\r\n"
    for offset in offsets:
        pdf += f"{offset:010d} 00000 n\r\n".encode()
    pdf += f"trailer\n<< /Size {size} /Root 1 0 R >>\n".encode()
    pdf += f"startxref\n{xref_offset}\n%%EOF".encode()
    return bytes(pdf)


def make_pdf_without_text() -> bytes:
    """PDF с пустым содержимым страницы — текст извлечь нельзя (имитация скана)."""
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R >>",
        b"<< /Length 0 >>\nstream\n\nendstream",
    ]
    pdf = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf += f"{index} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref_offset = len(pdf)
    size = len(objects) + 1
    pdf += f"xref\n0 {size}\n".encode()
    pdf += b"0000000000 65535 f\r\n"
    for offset in offsets:
        pdf += f"{offset:010d} 00000 n\r\n".encode()
    pdf += f"trailer\n<< /Size {size} /Root 1 0 R >>\n".encode()
    pdf += f"startxref\n{xref_offset}\n%%EOF".encode()
    return bytes(pdf)


# Тексты с непересекающимся словарём — гарантируют match / no_match.
ORIGINAL_TEXT = (
    "Sertifikat podtverzhdaet uspeshnoe okonchanie kursa programmirovaniya "
    "Python uchastnikom Ivan Petrov nomer ABC alpha bravo charlie delta echo"
)
DIFFERENT_TEXT = (
    "Kvitanciya ob oplate kommunalnyh uslug zhilischnaya sluzhba gorod "
    "raschet period oktyabr zulu yankee xray whiskey victor uniform tango"
)


def create_company(client, name="ООО Тест", email="test@example.com"):
    """Создаёт компанию и возвращает её JSON."""
    response = client.post("/companies", json={"name": name, "email": email})
    assert response.status_code == 201, response.text
    return response.json()


def issue_certificate(
    client,
    company_id,
    number="CERT-001",
    issue_date="2025-01-15",
    recipient="Иван Петров",
    text=ORIGINAL_TEXT,
):
    """Выпускает сертификат с PDF, содержащим заданный текст."""
    return client.post(
        "/certificates",
        data={
            "company_id": company_id,
            "certificate_number": number,
            "issue_date": issue_date,
            "recipient_name": recipient,
        },
        files={"file": ("cert.pdf", make_pdf(text), "application/pdf")},
    )
