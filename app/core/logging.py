import logging
import sys
from contextvars import ContextVar
from typing import Optional

from app.core.config import settings

# Context variable to hold request_id across async tasks/coroutines
correlation_id_ctx: ContextVar[str] = ContextVar("correlation_id", default="SYSTEM")


class CorrelationIdFilter(logging.Filter):
    """
    Log filter that dynamically injects the current request's 
    correlation ID into every log record.
    """
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = correlation_id_ctx.get()
        return True


def setup_logging(log_level: Optional[int] = None) -> None:
    """
    Configures centralized structured logging for the application.
    Includes timestamps, severity levels, correlation IDs, and file/line references.
    """
    if log_level is None:
        log_level = logging.DEBUG if settings.DEBUG else logging.INFO

    # Custom log format with [request_id]
    log_format = "%(asctime)s | %(levelname)-8s | [%(request_id)s] %(name)s:%(lineno)d - %(message)s"
    formatter = logging.Formatter(fmt=log_format, datefmt="%Y-%m-%d %H:%M:%S")

    # Console Handler
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    handler.addFilter(CorrelationIdFilter())

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Avoid duplicate handlers if setup_logging is called multiple times
    root_logger.handlers.clear()
    root_logger.addHandler(handler)

    # Silence overly verbose third-party loggers
    logging.getLogger("uvicorn.access").handlers.clear()
    logging.getLogger("uvicorn.access").propagate = False
