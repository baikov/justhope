"""CLI entrypoint.

Сейчас реализована одна команда: setup (алиас: base-setup).
В будущем сюда удобно добавлять подкоманды (туннели, сервисы и т.п.).
"""

from __future__ import annotations

import sys
from collections.abc import Sequence

from justhope import server_setup
from justhope.logging_config import log


def main(argv: Sequence[str] | None = None) -> int:
    args = list(argv) if argv is not None else sys.argv[1:]

    if not args or args[0] in {'-h', '--help'}:
        sys.stdout.write(
            'justhope\n\n'
            'Команды:\n'
            '  setup       Базовый hardening сервера (Ubuntu/Debian)\n'
            '  base-setup  Алиас для setup\n\n'
            'Пример:\n'
            '  justhope setup --user deploy --ssh-port 2222 --extra-ports 80 443\n'
        )
        return 0

    cmd, *rest = args
    if cmd in {'setup', 'base-setup'}:
        return server_setup.main(rest)

    log.error(f'Unknown command: {cmd}')
    log.info('Run: justhope --help')
    return 2
