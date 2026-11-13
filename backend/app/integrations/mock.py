from __future__ import annotations

import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

import fastapi
import httpx

from .models import CommentPayloadLike, OpenApiProfile, PublishResult


@dataclass(frozen=True, slots=True)
class MockRequest:
    method: str
    url: str
    headers: Mapping[str, str]
    body: bytes


class MockOpenApiAdapter:
    def __init__(
        self,
        *,
        changed_files: tuple[str, ...] | None = None,
        publish_results: Sequence[PublishResult] | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._changed_files = changed_files
        self._publish_results = tuple(publish_results or ())
        self._clock = clock
        self._lock = threading.Lock()
        self._comments: list[CommentPayloadLike] = []
        self._requests: list[MockRequest] = []
        self._cursor = 0

    def fetch_changed_files(self, repo: str, base_sha: str, head_sha: str) -> tuple[str, ...] | None:
        with self._lock:
            self._requests.append(
                MockRequest("GET", f"mock://changed/{repo}", {"X-Mock": ""}, b"")
            )
            return self._changed_files

    def publish_comment(self, repo: str, pr_number: int, payload: CommentPayloadLike) -> PublishResult:
        with self._lock:
            self._comments.append(payload)
            self._requests.append(
                MockRequest("POST", f"mock://comment/{repo}/{pr_number}", {"X-Mock": ""}, payload.markdown.encode("utf-8"))
            )
            if self._publish_results:
                index = min(self._cursor, len(self._publish_results) - 1)
                self._cursor += 1
                return self._publish_results[index]
            return PublishResult(
                success=True,
                status_code=201,
                comment_id=f"mock-comment-{len(self._comments)}",
                attempts=1,
                duration_ms=0,
                retried=False,
            )

    @property
    def comments(self) -> tuple[CommentPayloadLike, ...]:
        with self._lock:
            return tuple(self._comments)

    @property
    def requests(self) -> tuple[MockRequest, ...]:
        with self._lock:
            return tuple(self._requests)


class MockOpenApiService:
    def __init__(self, profile: OpenApiProfile | None = None) -> None:
        self._profile = profile
        self._lock = threading.Lock()
        self._requests: list[MockRequest] = []
        self._comments: list[str] = []
        self._app = fastapi.FastAPI(title="RepoGuard Mock OpenAPI", version="1.0.0")

        @self._app.post("/mock/repos/{repo:path}/pulls/{pr_number}/comments")
        def publish(repo: str, pr_number: int) -> dict[str, object]:
            with self._lock:
                self._comments.append(repo)
                self._requests.append(MockRequest("POST", f"/mock/{repo}/pulls/{pr_number}/comments", {}, b""))
                comment_id = f"mock-comment-{len(self._comments)}"
            return {"data": {"id": comment_id}}

        @self._app.get("/mock/repos/{repo:path}/compare")
        def changed(repo: str, base: str = "", head: str = "") -> dict[str, object]:
            del base, head
            with self._lock:
                self._requests.append(MockRequest("GET", f"/mock/{repo}", {}, b""))
            return {"data": {"changed_files": []}}

    @property
    def app(self) -> fastapi.FastAPI:
        return self._app

    @property
    def requests(self) -> tuple[MockRequest, ...]:
        with self._lock:
            return tuple(self._requests)

    def transport(self) -> httpx.ASGITransport:
        return httpx.ASGITransport(app=self._app)


def build_mock_service(profile: OpenApiProfile | None = None) -> MockOpenApiService:
    return MockOpenApiService(profile)