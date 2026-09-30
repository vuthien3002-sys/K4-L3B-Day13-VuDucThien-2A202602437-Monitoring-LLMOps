from __future__ import annotations

import re
import time
import uuid

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from structlog.contextvars import bind_contextvars, clear_contextvars

REQUEST_ID_HEADER = "x-request-id"
REQUEST_ID_PATTERN = re.compile(r"^req-[0-9a-f]{8}$")


def new_correlation_id() -> str:
    return f"req-{uuid.uuid4().hex[:8]}"


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Xóa context của request trước để log không bị lẫn giữa các request
        clear_contextvars()

        # Chỉ nhận ID từ client khi đúng format req-<8-hex>; sai format thì sinh mới
        # để tránh client chèn giá trị tùy ý vào log.
        incoming = request.headers.get(REQUEST_ID_HEADER, "").strip().lower()
        correlation_id = incoming if REQUEST_ID_PATTERN.match(incoming) else new_correlation_id()

        bind_contextvars(correlation_id=correlation_id)
        request.state.correlation_id = correlation_id

        start = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - start) * 1000

        response.headers[REQUEST_ID_HEADER] = correlation_id
        response.headers["x-response-time-ms"] = f"{elapsed_ms:.1f}"

        return response
