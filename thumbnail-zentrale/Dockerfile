# Thumbnail-Zentrale: Python + Chromium (zum Rendern der Thumbnails)
FROM mcr.microsoft.com/playwright/python:v1.49.1-noble

ENV PYTHONUNBUFFERED=1 \
    DATA_DIR=/data \
    PORT=8080 \
    TZ=Europe/Berlin

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

# Version für die Fußzeile (setzt GitHub Actions beim Bauen)
ARG APP_VERSION=dev
ARG APP_BUILT=
ENV APP_VERSION=$APP_VERSION \
    APP_BUILT=$APP_BUILT

VOLUME /data
EXPOSE 8080
HEALTHCHECK --interval=1m --timeout=10s CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/api/stand')" || exit 1
CMD ["python", "server.py"]
