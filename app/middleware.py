from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from typing import Any

from starlette.responses import JSONResponse


class RequestSizeLimitMiddleware:
    """Cap the multipart request before Starlette parses or spools uploaded files."""

    def __init__(self, app, max_bytes: int, path: str = "/api/ingest"):
        self.app = app
        self.max_bytes = max_bytes
        self.path = path

    async def __call__(self, scope: dict[str, Any], receive, send) -> None:
        if scope.get("type") != "http" or scope.get("path") != self.path or scope.get("method") != "POST":
            await self.app(scope, receive, send)
            return
        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        try:
            content_length = int(headers.get(b"content-length", b"0"))
        except ValueError:
            content_length = self.max_bytes + 1
        if content_length > self.max_bytes:
            await JSONResponse({"detail": "Upload request exceeds the aggregate size limit."}, status_code=413)(scope, receive, send)
            return
        messages = []
        received = 0
        while True:
            message = await receive()
            messages.append(message)
            if message.get("type") == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    await JSONResponse({"detail": "Upload request exceeds the aggregate size limit."}, status_code=413)(scope, receive, send)
                    return
                if not message.get("more_body", False):
                    break
            elif message.get("type") == "http.disconnect":
                return

        async def replay_receive():
            return messages.pop(0) if messages else {"type": "http.disconnect"}

        await self.app(scope, replay_receive, send)


class InMemoryRateLimitMiddleware:
    """Small single-instance guard for expensive local-prototype endpoints."""

    def __init__(self, app, limits: dict[str, tuple[int, int]]):
        self.app = app
        self.limits = limits
        self.events: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self.lock = threading.Lock()

    async def __call__(self, scope: dict[str, Any], receive, send) -> None:
        path = scope.get("path", "")
        if scope.get("type") != "http" or scope.get("method") != "POST" or path not in self.limits:
            await self.app(scope, receive, send)
            return
        limit, window_seconds = self.limits[path]
        client = scope.get("client") or ("local", 0)
        key = (str(client[0]), path)
        now = time.monotonic()
        with self.lock:
            events = self.events[key]
            while events and events[0] <= now - window_seconds:
                events.popleft()
            allowed = len(events) < limit
            if allowed:
                events.append(now)
        if not allowed:
            await JSONResponse(
                {"detail": "Rate limit reached for this expensive operation."}, status_code=429,
                headers={"Retry-After": str(window_seconds)},
            )(scope, receive, send)
            return
        await self.app(scope, receive, send)
