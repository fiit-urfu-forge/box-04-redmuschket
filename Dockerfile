FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# System packages required by psycopg2 / pdfplumber runtime
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Страховка от CRLF: убираем возможные \r из скрипта (если контекст сборки
# был выгружен на Windows), затем делаем его исполняемым.
RUN sed -i 's/\r$//' /app/entrypoint.sh \
    && chmod +x /app/entrypoint.sh \
    && mkdir -p storage/certificates storage/suspicious storage/archive models logs

EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]
