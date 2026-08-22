FROM python:3.12-slim
WORKDIR /app
ARG APP_VERSION=unknown
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_VERSION=${APP_VERSION}
LABEL org.opencontainers.image.title="MAM-Shelfbound" \
      org.opencontainers.image.description="Search MyAnonamouse, add audiobooks to Transmission, and import them into Audiobookshelf" \
      org.opencontainers.image.version="${APP_VERSION}"
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN mkdir -p /storage /ebooks /ebooks-nosend \
    && ln -s /storage/downloads /downloads \
    && ln -s /storage/audiobooks /library
COPY app/ /app/
EXPOSE 8080
CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}"]
