"""Shared logging, metrics and health endpoints.

This file is intentionally identical in every service (a copy, not a shared
library). Turning it into a shared package is one of the refactoring exercises.
"""
import json
import logging
import time

from fastapi import FastAPI, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

REQUESTS = Counter(
    "http_requests_total", "Total HTTP requests", ["service", "method", "path", "status"]
)
LATENCY = Histogram(
    "http_request_duration_seconds", "HTTP request latency", ["service", "method", "path"]
)


class JsonFormatter(logging.Formatter):
    """One JSON object per log line, which log tools (Loki, ELK) can parse."""

    def __init__(self, service: str):
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(
            {
                "ts": self.formatTime(record),
                "level": record.levelname,
                "service": self.service,
                "logger": record.name,
                "msg": record.getMessage(),
            }
        )


def setup_logging(service: str) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter(service))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)


def instrument(app: FastAPI, service: str) -> None:
    """Add request metrics, /health (liveness) and /metrics (Prometheus)."""

    @app.middleware("http")
    async def metrics_middleware(request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        route = request.scope.get("route")
        path = route.path if route else "unmatched"
        REQUESTS.labels(service, request.method, path, response.status_code).inc()
        LATENCY.labels(service, request.method, path).observe(time.perf_counter() - start)
        return response

    @app.get("/health", tags=["ops"])
    def health():
        # Liveness: "the process is up". It must NOT check dependencies.
        return {"status": "ok", "service": service}

    @app.get("/metrics", tags=["ops"])
    def metrics():
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
