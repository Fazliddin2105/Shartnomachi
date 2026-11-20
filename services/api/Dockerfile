# syntax=docker/dockerfile:1.7
# Build from the repository root:  docker build -f services/api/Dockerfile -t lexlab-api .
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

FROM base AS builder
WORKDIR /build
COPY services/api/requirements.txt .
RUN pip wheel --wheel-dir /wheels -r requirements.txt

FROM base AS runtime
ARG WITH_LIBREOFFICE=false
# OCR (uz-Latn, uz-Cyrl, ru) + PDF rasterisation; LibreOffice optional for DOCX->PDF
RUN apt-get update && apt-get install -y --no-install-recommends \
      tesseract-ocr tesseract-ocr-uzb tesseract-ocr-uzb-cyrl tesseract-ocr-rus poppler-utils \
    && if [ "$WITH_LIBREOFFICE" = "true" ]; then apt-get install -y --no-install-recommends libreoffice-writer-nogui; fi \
    && rm -rf /var/lib/apt/lists/*
RUN useradd --create-home --uid 10001 app
WORKDIR /srv/api
COPY --from=builder /wheels /wheels
RUN pip install /wheels/* && rm -rf /wheels
COPY --chown=app:app services/api/ .
COPY --chown=app:app packages/legal-content /srv/packages/legal-content
COPY --chown=app:app packages/contracts/build /srv/packages/contracts/build
ENV LEGAL_CONTENT_DIR=/srv/packages/legal-content
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/health/live')"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
