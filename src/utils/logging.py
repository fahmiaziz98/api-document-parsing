import sys

from loguru import logger


def setup_logging(level: str = "INFO") -> None:
    """
    Setup logging configuration

    Args:
        level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    """
    logger.remove()
    logger.add(
        sys.stdout,
        level=level,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level:<8}</level> | <cyan>{name}</cyan>:<cyan>{line}</cyan> - {message}",
        colorize=True,
    )
    logger.add(
        "logs/parser.log",
        level="DEBUG",
        rotation="100 MB",
        retention="7 days",
        compression="zip",
    )
