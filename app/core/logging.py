import logging
import os
import sys
from contextvars import ContextVar
from typing import Optional

from app.core.config import settings

# Initialize Windows virtual terminal processing so ANSI escape sequences render colors in CMD/PowerShell
if sys.platform == "win32":
    os.system("")

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


class ColoredFormatter(logging.Formatter):
    """
    Custom formatter that colors log levels and metadata for enhanced terminal readability:
    - DEBUG:    Cyan
    - INFO:     Green
    - WARNING:  Yellow
    - ERROR:    Red
    - CRITICAL: Bold Red
    - Correlation ID: Magenta
    - Timestamp: Dim/Gray
    """
    RESET = "\033[0m"
    GRAY = "\033[90m"
    MAGENTA = "\033[35m"
    BLUE = "\033[34m"

    LEVEL_COLORS = {
        logging.DEBUG: "\033[36m",       # Cyan
        logging.INFO: "\033[32m",        # Green
        logging.WARNING: "\033[33m",     # Yellow
        logging.ERROR: "\033[31m",       # Red
        logging.CRITICAL: "\033[1;31m",  # Bold Red
    }

    def format(self, record: logging.LogRecord) -> str:
        color = self.LEVEL_COLORS.get(record.levelno, self.RESET)

        # Colorized severity level (padded to 8 chars)
        colored_level = f"{color}{record.levelname:<8}{self.RESET}"

        # Colorized correlation ID
        req_id = getattr(record, "request_id", "SYSTEM")
        colored_req_id = f"[{self.MAGENTA}{req_id}{self.RESET}]"

        # Dimmed timestamp
        timestamp = f"{self.GRAY}{self.formatTime(record, self.datefmt)}{self.RESET}"

        # Location module and line number
        location = f"{self.BLUE}{record.name}:{record.lineno}{self.RESET}"

        # Message (colored for errors/critical, normal otherwise)
        msg = record.getMessage()
        if record.levelno >= logging.ERROR:
            msg = f"{color}{msg}{self.RESET}"

        return f"{timestamp} | {colored_level} | {colored_req_id} {location} - {msg}"


def setup_logging(log_level: Optional[int] = None) -> None:
    """
    Configures centralized structured logging with ANSI color-coded severities.
    Uses sys.stderr so logs appear instantaneously in PowerShell/CMD terminals.
    """
    if log_level is None:
        log_level = logging.DEBUG if settings.DEBUG else logging.INFO

    # Custom colored formatter
    formatter = ColoredFormatter(datefmt="%Y-%m-%d %H:%M:%S")

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
