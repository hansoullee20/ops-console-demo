"""Health endpoint — the only route Phase 1 exposes."""

from __future__ import annotations

from fastapi import APIRouter, Response, status

from app.schemas.health import HealthResponse
from app.services import health as health_service

APP_NAME = "ops-console-backend"
PHASE = 2

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def get_health(response: Response) -> HealthResponse:
    report = health_service.health_report()
    if report["status"] != "ok":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthResponse(app=APP_NAME, phase=PHASE, **report)
