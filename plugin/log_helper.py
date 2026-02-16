"""Logging utilities for the reMarkable Calibre plugin."""
import functools
import logging

_log = logging.getLogger(__name__)


def trace_calls(fn):
    """Decorator that logs function entry with arguments at DEBUG level."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        _log.debug("-> %s(args=%s, kwargs=%s)", fn.__qualname__, args, kwargs)
        return fn(*args, **kwargs)
    return wrapper
