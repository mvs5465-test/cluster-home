FROM python:3.14-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=8080
ENV PROMETHEUS_MULTIPROC_DIR=/tmp/prometheus-multiproc

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py gunicorn.conf.py wsgi.py ./
COPY config ./config
COPY templates ./templates
COPY static ./static

EXPOSE 8080

CMD ["sh", "-c", "mkdir -p \"${PROMETHEUS_MULTIPROC_DIR}\" && find \"${PROMETHEUS_MULTIPROC_DIR}\" -type f -delete && gunicorn --config gunicorn.conf.py --bind 0.0.0.0:${PORT} --workers 2 --threads 4 --timeout 60 wsgi:app"]
