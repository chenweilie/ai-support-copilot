"""
Observability: Structured logging with Loguru.
"""
from __future__ import annotations

import sys
from loguru import logger as _logger


def setup_logging(level: str = "INFO") -> None:
    _logger.remove()
    _logger.add(
        sys.stdout,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{line}</cyan> | "
            "{message} | {extra}"
        ),
        level=level,
        colorize=True,
        serialize=False,
    )
    # JSON log file for ingestion into monitoring stacks
    _logger.add(
        "logs/app.jsonl",
        format="{message}",
        level="DEBUG",
        rotation="10 MB",
        retention="7 days",
        serialize=True,
    )


def get_logger(name: str):
    return _logger.bind(module=name)
