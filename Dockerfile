FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app \
    PORT=8000

RUN apt-get update \
  && apt-get install -y --no-install-recommends \
    libglib2.0-0 \
    libgomp1 \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --upgrade pip \
  && pip install -r /app/backend/requirements.txt

COPY backend /app/backend
COPY scripts /app/scripts

RUN adduser --disabled-password --gecos "" appuser \
  && chown -R appuser:appuser /app

USER appuser
ENV HOME=/home/appuser

CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT}"]
