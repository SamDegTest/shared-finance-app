# ==============================================================================
# 1. Builder Stage: Build Python dependencies & download NLP models
# ==============================================================================
FROM python:3.12-slim AS builder

WORKDIR /build

# Install OS build dependencies & Tesseract OCR headers
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    tesseract-ocr \
    libtesseract-dev \
    tesseract-ocr-ita \
    tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt

# Download spaCy large NLP model for Microsoft Presidio PII entity detection
RUN python -m spacy download en_core_web_lg

# ==============================================================================
# 2. Runner Stage: Hardened, production container with local OCR & Presidio SDK
# ==============================================================================
FROM python:3.12-slim AS runner

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    PORT=8000 \
    TESSDATA_PREFIX=/usr/share/tesseract-ocr/5/tessdata

# Install runtime dependencies (curl for healthcheck, Tesseract OCR runtime & language packs)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    tesseract-ocr \
    libtesseract-dev \
    tesseract-ocr-ita \
    tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

# Crea utente di sistema non-root dedicato per sicurezza (hardening)
RUN groupadd --system --gid 1001 appgroup && \
    useradd --system --uid 1001 --gid appgroup --create-home appuser

# Copia l'ambiente virtuale compilato dal builder (incluso modello spaCy)
COPY --from=builder /opt/venv /opt/venv

# Copia il codice dell'applicazione e le configurazioni
COPY --chown=appuser:appgroup app/ ./app/
COPY --chown=appuser:appgroup alembic/ ./alembic/
COPY --chown=appuser:appgroup alembic.ini pyproject.toml ./

# Crea directory per uploads con permessi corretti
RUN mkdir -p uploads/receipts && chown -R appuser:appgroup uploads/

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --start-period=15s --retries=3 \
  CMD curl --fail http://localhost:8000/api/v1/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--no-access-log"]
