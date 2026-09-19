import logging
import time
import uuid
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging import correlation_id_ctx

logger = logging.getLogger("app.middleware")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    Outer-boundary middleware that:
    1. Extracts or generates a unique correlation ID (request_id) per request.
    2. Measures HTTP execution latency in milliseconds.
    3. Logs request arrival and completion.
    4. Attaches 'X-Request-ID' and 'X-Process-Time' to the HTTP response headers.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        # 1. Obtain or generate correlation ID (use first 8 hex chars for readability)
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:8]
        token = correlation_id_ctx.set(request_id)

        client_ip = request.client.host if request.client else "unknown"
        start_time = time.perf_counter()

        logger.info(f"──> {request.method} {request.url.path} [Client: {client_ip}]")

        try:
            response = await call_next(request)
            duration_ms = (time.perf_counter() - start_time) * 1000

            logger.info(
                f"<── {request.method} {request.url.path} {response.status_code} ({duration_ms:.1f}ms)"
            )

            # Inject diagnostic headers for frontend/client observability
            response.headers["X-Request-ID"] = request_id
            response.headers["X-Process-Time"] = f"{duration_ms:.2f}ms"

            return response

        except Exception as exc:
            duration_ms = (time.perf_counter() - start_time) * 1000
            logger.error(
                f"<── {request.method} {request.url.path} FAILED with {type(exc).__name__} ({duration_ms:.1f}ms): {exc}"
            )
            raise exc

        finally:
            # Clean up context to avoid leaking into recycled thread workers
            correlation_id_ctx.reset(token)
