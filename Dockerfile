FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN useradd --create-home --shell /usr/sbin/nologin appuser

COPY requirements.txt pyproject.toml README.md ./
COPY src ./src
COPY app ./app
COPY config ./config

RUN python -m pip install --upgrade pip \
    && python -m pip install -r requirements.txt \
    && python -m pip install -e .

RUN mkdir -p /app/data \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000 8501
