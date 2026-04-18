"""CLI entrypoint.

Сейчас реализованы команды: setup, update.
В будущем сюда удобно добавлять подкоманды (туннели, сервисы и т.п.).
"""

from __future__ import annotations

import sys
from collections.abc import Sequence

from justhope import server_setup
from justhope.logging_config import log
from justhope.updater import DEFAULT_SPEC, UpdateOptions, update_self


def main(argv: Sequence[str] | None = None) -> int:
    args = list(argv) if argv is not None else sys.argv[1:]

    if not args or args[0] in {'-h', '--help'}:
        sys.stdout.write(
            'justhope\n\n'
            'Команды:\n'
            '  setup       Базовый hardening сервера (Ubuntu/Debian)\n'
            '  update      Обновить justhope из GitHub в текущем окружении\n\n'
            'Параметры setup: justhope setup --help\n'
            'Коротко по флагам:\n'
            '  --user - имя пользователя для создания (по умолчанию: user)\n'
            '  --ssh-key - ключ для SSH одной строкой\n'
            '  --ssh-port - порт для SSH (по умолчанию: 22)\n'
            '  --extra-ports - дополнительные порты для открытия в UFW\n'
            '  --no-upgrade - не выполнять обновление системы\n'
            '  --no-swap - не пытаться создать swap файл\n'
            '  --no-zsh - не устанавливать zsh\n'
            '  --no-ohmyzsh - не устанавливать oh-my-zsh\n'
            '  --no-base-packages - не устанавливать базовые пакеты\n\n'
            'Пример:\n'
            '  justhope setup --user user --ssh-port 2222 --extra-ports 80 443\n'
        )
        return 0

    cmd, *rest = args
    if cmd == 'setup':
        return server_setup.main(rest)

    if cmd == 'update':
        spec = DEFAULT_SPEC
        prefer_uv = True

        it = iter(rest)
        for arg in it:
            if arg == '--spec':
                try:
                    spec = next(it)
                except StopIteration:
                    log.error('update: ожидается значение после --spec')
                    return 2
            elif arg == '--no-uv':
                prefer_uv = False
            elif arg in {'-h', '--help'}:
                sys.stdout.write(
                    'justhope update\n\n'
                    'Опции:\n'
                    f'  --spec <url>  Пакет/URL для установки (по умолчанию: {DEFAULT_SPEC})\n'
                    '  --no-uv       Не использовать uv, обновлять через pip\n'
                )
                return 0
            else:
                log.error(f'update: неизвестный аргумент: {arg}')
                return 2

        return update_self(UpdateOptions(spec=spec, prefer_uv=prefer_uv))

    log.error(f'Unknown command: {cmd}')
    log.info('Run: justhope --help')
    return 2
