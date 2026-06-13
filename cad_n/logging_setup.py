"""Logging configuration.

Design principle from the doc (section 12.3): *log both, show one*. Developers
get a full rotating log file with stack traces; operators get plain-English
warnings in the UI. This module wires up the developer-facing file + console
log. Operator warnings are carried separately as ``Warning`` objects on the
import / nesting results, not through this logger.
"""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

_CONFIGURED = False


def data_dir() -> Path:
    """Per-user data directory (best-nest log, etc.) that survives packaging."""
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    root = Path(base) if base else Path.home()
    d = root / "CAD-N"
    d.mkdir(parents=True, exist_ok=True)
    return d


def log_dir() -> Path:
    """Per-user log directory that survives packaging as an .exe."""
    d = data_dir() / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def configure(level: int = logging.INFO, to_file: bool = True) -> logging.Logger:
    """Configure root logging once. Safe to call repeatedly."""
    global _CONFIGURED
    logger = logging.getLogger("cad_n")
    if _CONFIGURED:
        return logger
    logger.setLevel(logging.DEBUG)
    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-7s %(name)s:%(lineno)d  %(message)s"
    )

    console = logging.StreamHandler()
    console.setLevel(level)
    console.setFormatter(fmt)
    logger.addHandler(console)

    if to_file:
        try:
            fh = RotatingFileHandler(
                log_dir() / "cad_n.log",
                maxBytes=2_000_000,
                backupCount=3,
                encoding="utf-8",
            )
            fh.setLevel(logging.DEBUG)
            fh.setFormatter(fmt)
            logger.addHandler(fh)
        except OSError:
            # Never let logging setup crash the app.
            logger.warning("Could not open log file; continuing without it.")

    logger.propagate = False
    _CONFIGURED = True
    return logger


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"cad_n.{name}")
