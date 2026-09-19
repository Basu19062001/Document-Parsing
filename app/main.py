import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app.core import AppException, RequestLoggingMiddleware, settings, setup_logging
from app.routes import api_router

logger = logging.getLogger("app.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application Lifespan Management:
    Initializes logging and verifies required directories on startup.
    """
    setup_logging()
    settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    logger.info(
        f"Starting {settings.PROJECT_NAME} in [{settings.ENVIRONMENT.upper()}] mode | "
        f"Upload dir: '{settings.UPLOAD_DIR}'"
    )
    yield
    logger.info(f"Shutting down {settings.PROJECT_NAME}...")


app = FastAPI(
    title=settings.PROJECT_NAME,
    version="0.1.0",
    description="Document parsing ingestion platform for GenAI applications.",
    lifespan=lifespan,
)

# 1. Register HTTP Boundary Middleware (Request ID & Latency Logging)
app.add_middleware(RequestLoggingMiddleware)


# 2. Register Centralized Exception Handlers (Clean Architecture Error Gateway)
@app.exception_handler(AppException)
async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
    """
    Translates any domain exception (Validation, Storage) into a 
    clean, RFC-compliant JSON response with machine-readable error codes.
    """
    logger.warning(
        f"Handled [{exc.error_code}] on {request.method} {request.url.path} "
        f"(HTTP {exc.status_code}): {exc.message}"
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error_code": exc.error_code,
            "message": exc.message,
            "details": exc.details,
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Catch-all safety net for unexpected crashes.
    Prevents leaking internal stack traces to clients.
    """
    logger.exception(f"Unhandled server crash on {request.method} {request.url.path}: {exc}")
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error_code": "INTERNAL_SERVER_ERROR",
            "message": "An unexpected error occurred while processing the request.",
            "details": {},
        },
    )


# 3. Mount Centralized API Router (/api/v1/...)
app.include_router(api_router, prefix="/api")


# 4. Core System Endpoints
@app.get("/health", tags=["Health"], summary="System health probe")
async def health_check():
    """Health check probe for load balancers and container orchestrators."""
    return {"status": "ok", "environment": settings.ENVIRONMENT}