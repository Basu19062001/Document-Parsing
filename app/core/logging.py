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
    Uses sys.stderr (unbuffered) so logs appear instantaneously in PowerShell/CMD terminals.
    """
    if log_level is None:
        log_level = logging.DEBUG if settings.DEBUG else logging.INFO

    # Custom log format with [request_id]
    log_format = "%(asctime)s | %(levelname)-8s | [%(request_id)s] %(name)s:%(lineno)d - %(message)s"
    formatter = logging.Formatter(fmt=log_format, datefmt="%Y-%m-%d %H:%M:%S")

    # Use sys.stderr: standard stream for logs, completely unbuffered on Windows/Linux
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(formatter)
    handler.addFilter(CorrelationIdFilter())

    # 1. Configure the root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.handlers.clear()
    root_logger.addHandler(handler)

    # 2. Configure the 'app' hierarchy explicitly
    app_logger = logging.getLogger("app")
    app_logger.setLevel(log_level)
    app_logger.handlers.clear()
    app_logger.addHandler(handler)
    app_logger.propagate = False
