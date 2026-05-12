"""
utils/logging_config.py — Shared logging setup for the full pipeline

WHY a shared config rather than per-module basicConfig:
- Calling logging.basicConfig() in multiple modules produces duplicate handlers
  if modules are imported in the same process. One configuration point prevents
  that.
- Cloud Run captures stdout/stderr. Structured JSON output (when USE_JSON_LOGGING=1)
  lets Cloud Logging parse severity, timestamps, and step names automatically.
- Local runs use a human-readable format with the same information.

Usage:
    from utils.logging_config import get_logger
    log = get_logger(__name__)
    log.info("fetched %d rows", n)
    log.warning("stale: %s is %d days behind", series, days)
    log.error("step failed: %s", exc)
"""

import logging
import os
import sys


def _configure_root() -> None:
    root = logging.getLogger()
    if root.handlers:
        return  # already configured — avoid duplicate handlers

    use_json = os.environ.get("USE_JSON_LOGGING", "").lower() in ("1", "true")

    if use_json:
        # Structured JSON for Cloud Logging
        import json

        class JsonFormatter(logging.Formatter):
            def format(self, record: logging.LogRecord) -> str:
                payload = {
                    "severity": record.levelname,
                    "message": record.getMessage(),
                    "logger": record.name,
                    "time": self.formatTime(record, self.datefmt),
                }
                if record.exc_info:
                    payload["exception"] = self.formatException(record.exc_info)
                return json.dumps(payload)

        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JsonFormatter())
    else:
        fmt = "%(asctime)s  %(levelname)-7s  %(name)-30s  %(message)s"
        datefmt = "%Y-%m-%d %H:%M:%S"
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter(fmt, datefmt))

    level = os.environ.get("LOG_LEVEL", "INFO").upper()
    root.setLevel(getattr(logging, level, logging.INFO))
    root.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    _configure_root()
    return logging.getLogger(name)
