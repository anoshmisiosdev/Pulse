"""Logging setup: JSON lines in production (CloudWatch/Datadog), plain in dev."""

from __future__ import annotations

import json
import logging

from app.core.config import settings


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            entry["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(entry)


def setup_logging() -> None:
    handler = logging.StreamHandler()
    if settings.is_production:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(levelname)s:%(name)s:%(message)s"))
    root = logging.getLogger()
    root.setLevel(settings.log_level)
    root.handlers[:] = [handler]
