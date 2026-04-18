"""Настройка логирования для justhope."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path


def configure_logging() -> logging.Logger:
    """Настраивает логирование так, чтобы код не падал под non-root.

    - Всегда логирует в stdout.
    - Под root дополнительно пытается писать в /var/log/base_setup.log.
    """

    logger = logging.getLogger('justhope')
    logger.setLevel(logging.INFO)

    fmt = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')

    if not logger.handlers:
        stream = logging.StreamHandler(sys.stdout)
        stream.setFormatter(fmt)
        logger.addHandler(stream)

    if os.geteuid() == 0:
        log_path = Path('/var/log/base_setup.log')
        try:
            file_handler = logging.FileHandler(log_path)
            file_handler.setFormatter(fmt)
            if not any(isinstance(h, logging.FileHandler) for h in logger.handlers):
                logger.addHandler(file_handler)
        except OSError:
            pass

    return logger


log = configure_logging()
