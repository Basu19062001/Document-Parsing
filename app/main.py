import logging
from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI, Request, status
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse

from app.core import (
    AppException,
    RequestLoggingMiddleware,
    settings,
    setup_logging,
    verify_docs_credentials,
)
from app.routes import api_router

# Initialize structured logging immediately upon module load
setup_logging()

logger = logging.getLogger("app.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application Lifespan Management:
    Initializes logging, verifies storage directories, and logs startup URLs.
    """
    settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    logger.info(
        f"Starting {settings.PROJECT_NAME} in [{settings.ENVIRONMENT.upper()}] mode | "
        f"Upload dir: '{settings.UPLOAD_DIR}'"
    )
    logger.info("Swagger UI (Protected): /docs")
    logger.info("ReDoc (Protected): /redoc")
    logger.info("Health check endpoint: /health")
    yield
    logger.info(f"Shutting down {settings.PROJECT_NAME}...")


app = FastAPI(
    title=settings.PROJECT_NAME,
    version="0.1.0",
    description="Document parsing ingestion platform for GenAI applications.",
    lifespan=lifespan,
    docs_url=None,     # Protected via custom endpoint below
    redoc_url=None,    # Protected via custom endpoint below
    openapi_url=None,  # Protected via custom endpoint below
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


# 4. Core System Endpoint
@app.get("/health", tags=["Health"], summary="System health probe")
async def health_check():
    """Public health check probe for load balancers and container orchestrators."""
    logger.info(f"Health probe check invoked. Status: healthy | Environment: {settings.ENVIRONMENT}")
    return {"status": "ok", "environment": settings.ENVIRONMENT}


# 5. Protected Documentation Endpoints (HTTP Basic Auth)
@app.get("/docs", include_in_schema=False)
async def custom_swagger_ui_html(username: str = Depends(verify_docs_credentials)):
    """Swagger UI documentation interface protected by HTTP Basic Auth."""
    logger.info(f"Swagger UI accessed by authorized user: '{username}'")
    return get_swagger_ui_html(
        openapi_url="/openapi.json",
        title=f"{app.title} - Swagger UI",
    )


@app.get("/redoc", include_in_schema=False)
async def custom_redoc_html(username: str = Depends(verify_docs_credentials)):
    """ReDoc documentation interface protected by HTTP Basic Auth."""
    logger.info(f"ReDoc accessed by authorized user: '{username}'")
    return get_redoc_html(
        openapi_url="/openapi.json",
        title=f"{app.title} - ReDoc",
    )


@app.get("/openapi.json", include_in_schema=False)
async def custom_openapi_json(username: str = Depends(verify_docs_credentials)):
    """OpenAPI schema specification protected by HTTP Basic Auth."""
    logger.debug(f"OpenAPI schema requested by authorized user: '{username}'")
    return get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )