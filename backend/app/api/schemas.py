from __future__ import annotations

from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict


class ReviewRequest(BaseModel):
    manifest: str
    repo: str
    model_config = ConfigDict(extra="ignore")


class ErrorBody(BaseModel):
    code: str
    message: str
    detail: str | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody
    request_id: str


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    service: Literal["repoguard-web-api"]
    version: str
    engine: Literal["available", "unavailable"]
    default_repo: str | None
    allowed_repo_root_count: int
    time: str


def error_payload(
    code: str,
    message: str,
    detail: str | None = None,
    request_id: str | None = None,
) -> dict[str, object]:
    body: dict[str, object] = {"code": code, "message": message}
    if detail is not None:
        body["detail"] = detail
    return {
        "error": body,
        "request_id": request_id or uuid4().hex,
    }