#install the package and build

FROM python:3.12-slim AS builder

WORKDIR /app

ARG SERVICE

COPY services/${SERVICE}/requirements.txt .

RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# STAGE 2

FROM python:3.12-slim

WORKDIR /app

COPY --from=builder /install /usr/local

ARG SERVICE

COPY services/${SERVICE}/app ./app

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

RUN useradd --create-home --uid 10001 appuser \
    && mkdir /data \
    && chown appuser:appuser /data

USER appuser   

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

