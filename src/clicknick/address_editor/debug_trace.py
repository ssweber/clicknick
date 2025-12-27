"""Debug tracing utilities for Address Editor performance analysis.

Enable tracing by running with clicknick-debug, which sends output to console.
The DEBUG_PERF flag controls whether performance timing is logged.

Usage:
    from .debug_trace import logger, perf_timer, DEBUG_PERF

    # Simple logging
    logger.debug("Starting operation")

    # Performance timing (only logs if DEBUG_PERF is True)
    with perf_timer("operation_name"):
        do_expensive_work()

    # Or use the decorator
    @log_perf
    def expensive_function():
        pass
"""

from __future__ import annotations

import logging
import sys
import time
from collections.abc import Callable
from contextlib import contextmanager
from functools import wraps
from typing import Any

# Global flag to enable/disable performance tracing
# Set to True to enable detailed timing logs
DEBUG_PERF = True

# Create module logger
logger = logging.getLogger("clicknick.address_editor")


def setup_debug_logging() -> None:
    """Configure logging for debug mode (console output).

    Call this once at startup when running in debug mode.
    """
    # Only configure if not already configured
    if logger.handlers:
        return

    # Check if we're in debug mode (console attached)
    # clicknick-debug entry point has console, clicknick does not
    is_debug = sys.stdout is not None and hasattr(sys.stdout, "write")

    if is_debug:
        logger.setLevel(logging.DEBUG)
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(logging.DEBUG)
        formatter = logging.Formatter(
            "%(asctime)s.%(msecs)03d [%(levelname)s] %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    else:
        # In non-debug mode, only log warnings and above
        logger.setLevel(logging.WARNING)


@contextmanager
def perf_timer(operation: str, row_count: int | None = None):
    """Context manager for timing operations.

    Args:
        operation: Name of the operation being timed
        row_count: Optional row count for context

    Example:
        with perf_timer("refresh_display", row_count=5000):
            panel._refresh_display()
    """
    if not DEBUG_PERF:
        yield
        return

    start = time.perf_counter()
    try:
        yield
    finally:
        elapsed_ms = (time.perf_counter() - start) * 1000
        if row_count is not None:
            logger.debug(f"PERF: {operation} ({row_count} rows) took {elapsed_ms:.2f}ms")
        else:
            logger.debug(f"PERF: {operation} took {elapsed_ms:.2f}ms")


def log_perf(func: Callable) -> Callable:
    """Decorator to log function performance.

    Example:
        @log_perf
        def _validate_all(self):
            ...
    """

    @wraps(func)
    def wrapper(*args, **kwargs) -> Any:
        if not DEBUG_PERF:
            return func(*args, **kwargs)

        start = time.perf_counter()
        try:
            return func(*args, **kwargs)
        finally:
            elapsed_ms = (time.perf_counter() - start) * 1000
            logger.debug(f"PERF: {func.__qualname__} took {elapsed_ms:.2f}ms")

    return wrapper


# Initialize logging when module is imported
setup_debug_logging()
