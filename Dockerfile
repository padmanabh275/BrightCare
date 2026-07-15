FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY api ./api

RUN mkdir -p /data

ENV TELEGRAM_MODE=webhook
ENV SESSION_STORE=sqlite
ENV DATA_DIR=/data
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

# Render/Railway set $PORT; default 8000 for local Docker
CMD ["sh", "-c", "uvicorn api.index:app --host 0.0.0.0 --port ${PORT:-8000}"]
