# One image for the API and the worker (different command).
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
 && playwright install --with-deps chromium \
 && useradd -m app && mkdir -p /data/files && chown -R app /data /ms-playwright
COPY . .
USER app
ENV STORAGE_DIR=/data/files
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
# worker: docker run <image> python -m app.worker   |   migrations: alembic upgrade head
