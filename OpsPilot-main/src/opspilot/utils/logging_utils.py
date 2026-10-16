"""Structured JSON Lines logger for OpsPilot pipeline observability."""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional


class JSONLinesFormatter(logging.Formatter):
    """Formats log records as structured JSON lines."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.fromtimestamp(record.created).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if hasattr(record, "pipeline_stage"):
            log_entry["pipeline_stage"] = getattr(record, "pipeline_stage")
        if hasattr(record, "extra_data"):
            log_entry["data"] = getattr(record, "extra_data")
        return json.dumps(log_entry)


def get_logger(name: str = "opspilot", log_file: Optional[Path] = None) -> logging.Logger:
    """Returns a configured structured logger."""
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if not logger.handlers:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s"))
        logger.addHandler(console_handler)

        if log_file:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            file_handler = logging.FileHandler(log_file, encoding="utf-8")
            file_handler.setFormatter(JSONLinesFormatter())
            logger.addHandler(file_handler)

    return logger


def log_phase_transition(logger: logging.Logger, phase_name: str, status: str, details: Optional[Dict[str, Any]] = None):
    """Logs phase transitions with structured payload."""
    logger.info(
        f"PHASE TRANSITION -> {phase_name}: {status}",
        extra={
            "pipeline_stage": phase_name,
            "extra_data": details or {}
        }
    )
