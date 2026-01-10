"""
Logging module for ortler.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager

from termcolor import colored


class OrtlerLogFormatter(logging.Formatter):
    """
    Custom formatter for logging.
    """

    def format(self, record):
        message = record.getMessage()
        if record.levelno == logging.DEBUG:
            return colored(message, "magenta", force_color=True)
        elif record.levelno == logging.WARNING:
            return colored(message, "yellow", force_color=True)
        elif record.levelno in [logging.CRITICAL, logging.ERROR]:
            return colored(message, "red", force_color=True)
        else:
            return message


# Custom logger.
log = logging.getLogger("ortler")
log.setLevel(logging.INFO)
handler = logging.StreamHandler()
handler.setFormatter(OrtlerLogFormatter())
log.addHandler(handler)
log_levels = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
    "NO_LOG": logging.CRITICAL + 1,
}


@contextmanager
def mute_log(level=logging.ERROR):
    """
    Temporarily mute the log, simply works as follows:

    with mute_log():
       ...
    """
    original_level = log.getEffectiveLevel()
    log.setLevel(level)
    try:
        yield
    finally:
        log.setLevel(original_level)