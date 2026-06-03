import json
import sys
from typing import Any

from loguru import logger


def _json_serialize(record: dict) -> str:
    """
    Serialize a loguru record to JSON format for structured logging.

    Args:
        record: Loguru record dict

    Returns:
        JSON string with flattened fields
    """
    # Extract standard loguru fields
    log_entry: dict[str, Any] = {
        "timestamp": record["time"].isoformat(),
        "level": record["level"].name,
        "logger": record["name"],
        "message": record["message"],
    }

    # Add extra context fields (request_id, job_id, etc.)
    if record["extra"]:
        log_entry.update(record["extra"])

    return json.dumps(log_entry, ensure_ascii=False)


def setup_logging(level: str = "INFO", json_output: bool = True) -> None:
    """
    Setup logging configuration.

    In Modal container: json_output=True for structured JSON logs to stdout.
    In development: can override to json_output=False for colored output.

    Args:
        level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        json_output: If True, output structured JSON; else colored text
    """
    logger.remove()

    if json_output:
        # Structured JSON output to stdout (Modal captures this)
        def json_sink(message):
            """Custom sink that outputs JSON"""
            json_output_str = _json_serialize(message.record)
            sys.stdout.write(json_output_str + "\n")

        logger.add(
            json_sink,
            level=level,
            serialize=False,
        )
    else:
        # Colored text output for development
        logger.add(
            sys.stdout,
            level=level,
            format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level:<8}</level> | <cyan>{name}</cyan>:<cyan>{line}</cyan> - {message}",
            colorize=True,
        )
