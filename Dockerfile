FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-compile -r requirements.txt

COPY . .
RUN useradd --create-home appuser && mkdir -p /app/uploads && chown appuser /app/uploads
USER appuser

ENV PORT=8000
EXPOSE 8000
# Apply database migrations, then start the web server.
CMD alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips="*"
