import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

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
    1. Initializes logging and creates storage directories.
    2. Runs Alembic migrations automatically to ensure database tables exist.
    3. Logs service health and documentation endpoints.
    """
    settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    logger.info(
        f"Starting {settings.PROJECT_NAME} in [{settings.ENVIRONMENT.upper()}] mode | "
        f"Upload dir: '{settings.UPLOAD_DIR}'"
    )

    # Automatically verify and apply pending Alembic migrations
    try:
        from alembic.config import Config
        from alembic import command
        alembic_cfg = Config("alembic.ini")
        await asyncio.to_thread(command.upgrade, alembic_cfg, "head")
        logger.info("Database schema synchronized and up-to-date via Alembic.")
    except Exception as exc:
        logger.error(f"Failed to synchronize database migrations on startup: {exc}")

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
    Translates any domain exception (Validation, Storage, Database) into a 
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


@app.exception_handler(RequestValidationError)
async def request_validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """
    Translates FastAPI / Pydantic request parsing and query parameter errors
    into our RFC-compliant JSON error envelope (HTTP 422).
    """
    logger.warning(
        f"Request validation failed on {request.method} {request.url.path}: {exc.errors()}"
    )
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error_code": "REQUEST_VALIDATION_ERROR",
            "message": "The incoming request parameters or payload failed validation.",
            "details": {"errors": exc.errors()},
        },
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    """
    Translates framework HTTP exceptions (e.g. 404 Not Found, 405 Method Not Allowed)
    into our uniform JSON error envelope.
    """
    logger.warning(
        f"HTTP {exc.status_code} on {request.method} {request.url.path}: {exc.detail}"
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error_code": f"HTTP_{exc.status_code}",
            "message": str(exc.detail),
            "details": {},
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