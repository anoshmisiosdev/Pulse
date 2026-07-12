"""Application logging configuration with credential redaction."""

from __future__ import annotations

import logging
import re

from app.core.config import settings

_QUERY_SECRET_RE = re.compile(
    r"(?i)([?&](?:key|api_key|token|access_token|auth)=)[^&\s\"']+"
)
_BEARER_RE = re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+|bearer\s+)[^\s,;\"']+")


def redact_secrets(value: object) -> str:
    text = str(value)
    text = _QUERY_SECRET_RE.sub(r"\1<redacted>", text)
    return _BEARER_RE.sub(r"\1<redacted>", text)


class SecretRedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact_secrets(record.getMessage())
        record.args = ()
        return True


def configure_logging() -> None:
    logging.basicConfig(level=settings.log_level)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    redactor = SecretRedactionFilter()
    root = logging.getLogger()
    for handler in root.handlers:
        if not any(isinstance(item, SecretRedactionFilter) for item in handler.filters):
            handler.addFilter(redactor)
