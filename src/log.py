"""Log utilities."""

import logging
from rich.logging import RichHandler


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger configured for Rich console output.

    The returned logger has its level set to DEBUG, its handlers replaced with
    a single RichHandler for rich-formatted console output, and propagation to
    ancestor loggers disabled.

    Parameters:
        name (str): Name of the logger to retrieve or create.

    Returns:
        logging.Logger: The configured logger instance.
    """
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    logger.handlers = [RichHandler()]
    logger.propagate = False
    return logger
