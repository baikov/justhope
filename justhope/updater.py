"""Самообновление justhope из GitHub."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass

from .logging_config import log

DEFAULT_SPEC = 'git+https://github.com/baikov/justhope.git'


@dataclass(frozen=True)
class UpdateOptions:
    spec: str = DEFAULT_SPEC
    prefer_uv: bool = True


def _in_venv() -> bool:
    return bool(os.environ.get('VIRTUAL_ENV')) or (getattr(sys, 'base_prefix', sys.prefix) != sys.prefix)


def _run(cmd: list[str]) -> int:
    log.info('▶ ' + ' '.join(cmd))
    try:
        subprocess.run(cmd, check=True)  # noqa: S603
        return 0
    except subprocess.CalledProcessError as e:
        return int(e.returncode or 1)


def update_self(options: UpdateOptions | None = None) -> int:
    """Обновляет justhope в текущем Python-окружении.

    Возвращает код выхода (0 = ок).
    """

    opts = options or UpdateOptions()

    if not _in_venv():
        log.error(
            'Похоже, justhope запущен из системного Python без virtualenv. '
            'На Debian 12/13 pip может отказаться обновлять пакеты в систему (PEP 668).'
        )
        log.info('Рекомендовано: pipx/uvx для запуска, либо установка в venv (см. README).')
        return 2

    uv = shutil.which('uv') if opts.prefer_uv else None
    if uv:
        # uv pip установит/обновит пакет в текущем окружении.
        return _run([uv, 'pip', 'install', '-U', opts.spec])

    return _run([sys.executable, '-m', 'pip', 'install', '-U', opts.spec])
