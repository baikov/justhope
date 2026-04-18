"""Базовая настройка (hardening) сервера Ubuntu/Debian."""

from __future__ import annotations

import argparse
import os
import pwd
import shlex
import shutil
import subprocess
import tempfile
from collections.abc import Sequence
from pathlib import Path

from .logging_config import log


class ServerSetup:
    def __init__(
        self,
        username: str,
        ssh_key: str | None = None,
        ssh_port: int = 22,
        sudo: bool = True,
        extra_ports: list[int] | None = None,
    ):
        self.username = username
        self.ssh_key = ssh_key
        self.ssh_port = ssh_port
        self.sudo = sudo
        self.extra_ports = extra_ports or []
        self.home = Path(f'/home/{username}')
        self._ssh_access_ready: bool | None = None

    def _read_authorized_keys_lines(self, path: Path) -> list[str]:
        if not path.exists():
            return []
        # В authorized_keys может быть несколько строк. Держим их строками (без пустых).
        return [line.strip() for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]

    def _merge_authorized_keys(self, authorized_keys: Path, new_lines: list[str]) -> bool:
        """Добавляет отсутствующие строки в authorized_keys.

        Возвращает True, если в итоге в файле есть хотя бы один ключ.
        """
        existing = self._read_authorized_keys_lines(authorized_keys)
        existing_set = set(existing)

        to_add = [line for line in new_lines if line and line not in existing_set]
        if to_add:
            authorized_keys.parent.mkdir(parents=True, exist_ok=True)
            with authorized_keys.open('a', encoding='utf-8') as f:
                if existing:
                    f.write('\n')
                f.write('\n'.join(to_add) + '\n')

        # Перечитываем: могли создать/дописать
        final_lines = self._read_authorized_keys_lines(authorized_keys)
        self._run(['chown', f'{self.username}:{self.username}', str(authorized_keys)])
        self._run(['chmod', '600', str(authorized_keys)])
        return bool(final_lines)

    def _run(self, cmd: Sequence[str | os.PathLike], check: bool = True) -> subprocess.CompletedProcess:
        """Обёртка над subprocess с логированием."""
        cmd_str = [os.fspath(c) for c in cmd]
        log.debug(f'Executing: {" ".join(map(shlex.quote, cmd_str))}')
        try:
            return subprocess.run(cmd_str, capture_output=True, text=True, check=check)  # noqa: S603
        except subprocess.CalledProcessError as e:
            stderr = (e.stderr or '').strip()
            stdout = (e.stdout or '').strip()
            details = stderr if stderr else stdout
            log.error(f'Command failed (code={e.returncode}): {details}')
            raise

    def _ensure_user_ssh_dir(self) -> Path:
        user_ssh = self.home / '.ssh'
        user_ssh.mkdir(parents=True, exist_ok=True)
        self._run(['chown', '-R', f'{self.username}:{self.username}', str(user_ssh)])
        self._run(['chmod', '700', str(user_ssh)])
        return user_ssh

    def ensure_ssh_access(self) -> bool:
        """Гарантирует, что у пользователя есть публичный ключ в authorized_keys.

        Возвращает True, если ключ установлен/уже был, иначе False.
        """
        if self._ssh_access_ready is not None:
            return self._ssh_access_ready

        user_ssh = self._ensure_user_ssh_dir()
        authorized_keys = user_ssh / 'authorized_keys'

        # Если ключ передан строкой — добавляем только его и НЕ копируем root.
        if self.ssh_key:
            ok = self._merge_authorized_keys(authorized_keys, [self.ssh_key.strip()])
            self._ssh_access_ready = ok
            return ok

        # Иначе — копируем (мерджим) ключи из root.
        root_auth = Path('/root/.ssh/authorized_keys')
        root_lines = self._read_authorized_keys_lines(root_auth)
        if not root_lines:
            log.warning(
                '⚠️  Не найден /root/.ssh/authorized_keys. '
                'Парольный вход лучше не отключать, иначе можно потерять доступ.'
            )
            self._ssh_access_ready = False
            return False

        ok = self._merge_authorized_keys(authorized_keys, root_lines)
        self._ssh_access_ready = ok
        return ok

    def user_exists(self) -> bool:
        try:
            pwd.getpwnam(self.username)
            return True
        except KeyError:
            return False

    def create_user(self) -> None:
        if self.user_exists():
            log.info(f'✓ Пользователь {self.username} уже существует')
            return
        log.info(f'👤 Создаю пользователя {self.username}...')
        self._run(['useradd', '-m', '-s', '/bin/bash', self.username])

        user_ssh = self._ensure_user_ssh_dir()
        authorized_keys = user_ssh / 'authorized_keys'

        # По умолчанию переносим ключи root; если передан новый ключ — добавляем только его.
        if self.ssh_key:
            self._merge_authorized_keys(authorized_keys, [self.ssh_key.strip()])
        else:
            root_auth = Path('/root/.ssh/authorized_keys')
            root_lines = self._read_authorized_keys_lines(root_auth)
            if root_lines:
                self._merge_authorized_keys(authorized_keys, root_lines)

        log.info('✓ Пользователь создан')

    def setup_sudo(self) -> None:
        if not self.sudo:
            return
        log.info('🔐 Настраиваю sudo...')
        sudoers_entry = f'{self.username} ALL=(ALL) NOPASSWD:ALL'
        sudoers_file = Path(f'/etc/sudoers.d/{self.username}')

        if sudoers_file.exists() and sudoers_file.read_text().strip() == sudoers_entry:
            log.info('✓ sudo уже настроен')
            return

        fd, tmp_path = tempfile.mkstemp(prefix=f'sudoers_{self.username}_')
        tmp = Path(tmp_path)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                f.write(f'{sudoers_entry}\n')
            tmp.chmod(0o440)
            self._run(['chown', 'root:root', str(tmp)])
            self._run(['visudo', '-c', '-f', str(tmp)])
            shutil.move(str(tmp), str(sudoers_file))
        finally:
            if tmp.exists():
                tmp.unlink()

        log.info('✓ sudo настроен (NOPASSWD)')

    def setup_ssh(self) -> None:
        log.info(f'🔑 Настраиваю SSH (порт {self.ssh_port})...')
        sshd_config = Path('/etc/ssh/sshd_config')
        backup = sshd_config.with_suffix('.bak')

        if not backup.exists():
            shutil.copy2(sshd_config, backup)
            log.info('✓ Бэкап sshd_config создан')

        ssh_access_ready = self.ensure_ssh_access()

        settings = {
            'Port': str(self.ssh_port),
            'PermitRootLogin': 'prohibit-password',
            'PasswordAuthentication': 'no' if ssh_access_ready else 'yes',
            'PubkeyAuthentication': 'yes',
            'ClientAliveInterval': '300',
            'ClientAliveCountMax': '2',
        }

        content = sshd_config.read_text(encoding='utf-8')

        allow_users: set[str] = set()
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith('AllowUsers '):
                allow_users.update(stripped.split()[1:])
        allow_users.add(self.username)

        for key, value in settings.items():
            lines = [
                line
                for line in content.split('\n')
                if not line.strip().startswith(f'{key} ') and not line.strip().startswith(f'#{key} ')
            ]
            content = '\n'.join(lines)
            content += f'\n{key} {value}'

        lines = [
            line
            for line in content.split('\n')
            if not line.strip().startswith('AllowUsers ') and not line.strip().startswith('#AllowUsers ')
        ]
        content = '\n'.join(lines)
        content += '\nAllowUsers ' + ' '.join(sorted(allow_users))

        sshd_config.write_text(content.strip() + '\n')

        sshd_bin = shutil.which('sshd') or '/usr/sbin/sshd'
        try:
            self._run([sshd_bin, '-t', '-f', str(sshd_config)])
        except Exception as err:
            if backup.exists():
                shutil.copy2(backup, sshd_config)
            msg = 'sshd_config не прошёл проверку (sshd -t). Откатил на бэкап, reload не выполнен.'
            raise RuntimeError(msg) from err

        self._run(['systemctl', 'reload', 'ssh'])
        log.info('✓ SSH применён (sshd -t ok). Не закрывай текущую сессию, пока не проверишь новую!')

    def setup_ufw(self, allow_ports: list[int] | None = None) -> None:
        if allow_ports is None:
            allow_ports = [self.ssh_port]
        log.info('🔥 Настраиваю UFW...')

        if shutil.which('ufw') is None:
            self._run(['apt', 'update'])
            self._run(['apt', 'install', '-y', 'ufw'])

        status = self._run(['ufw', 'status'], check=False)
        if 'Status: inactive' in (status.stdout or ''):
            self._run(['ufw', '--force', 'enable'])

        self._run(['ufw', 'default', 'deny', 'incoming'])
        self._run(['ufw', 'default', 'allow', 'outgoing'])

        for port in allow_ports:
            self._run(['ufw', 'allow', f'{port}/tcp'])
            log.info(f'✓ Открыт порт {port}/tcp')

        status = self._run(['ufw', 'status'], check=False)
        if 'Status: inactive' in (status.stdout or ''):
            self._run(['ufw', '--force', 'enable'])

        log.info('✓ UFW настроен')

    def setup_fail2ban(self) -> None:
        log.info('🚫 Устанавливаю fail2ban...')
        self._run(['apt', 'update'])
        self._run(['apt', 'install', '-y', 'fail2ban'])

        jail_config = Path('/etc/fail2ban/jail.d/sshd.local')
        jail_config.parent.mkdir(parents=True, exist_ok=True)
        desired = (
            '[sshd]\n'
            'enabled = true\n'
            f'port = {self.ssh_port}\n'
            'filter = sshd\n'
            'logpath = /var/log/auth.log\n'
            'maxretry = 3\n'
            'bantime = 3600\n'
        )
        if not jail_config.exists() or jail_config.read_text(encoding='utf-8') != desired:
            jail_config.write_text(desired, encoding='utf-8')

        self._run(['systemctl', 'restart', 'fail2ban'])
        log.info('✓ fail2ban настроен')

    def run(self) -> None:
        log.info(f'🚀 Начинаю базовую настройку сервера для {self.username}')

        self.create_user()
        self.ensure_ssh_access()
        self.setup_sudo()
        self.setup_ssh()
        self.setup_ufw(allow_ports=[self.ssh_port, *self.extra_ports])
        self.setup_fail2ban()

        log.info('📦 Обновляю пакеты...')
        self._run(['apt', 'update'])
        self._run(['apt', 'upgrade', '-y'])

        log.info('✅ Готово! Проверь подключение под новым юзером:')
        log.info(f'   ssh -p {self.ssh_port} {self.username}@<server_ip>')
        log.info('⚠️  Не закрывай текущую сессию root, пока не убедишься, что новый логин работает!')


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Base server hardening')
    parser.add_argument('--user', required=True, help='Имя нового пользователя')
    parser.add_argument(
        '--ssh-key',
        help='Публичный SSH-ключ одной строкой (опционально). Если не задан, берём ключи из /root/.ssh/authorized_keys',
    )
    parser.add_argument('--ssh-port', type=int, default=2222, help='Порт SSH (по умолчанию 2222)')
    parser.add_argument('--no-sudo', action='store_true', help='Не добавлять в sudo')
    parser.add_argument('--extra-ports', nargs='+', type=int, default=[], help='Доп. порты для UFW (например, 80 443)')
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    if os.geteuid() != 0:
        log.error('❌ Запускай от root, дружище. justhope setup --user <name> ...')
        return 1

    args = parse_args(argv)

    setup = ServerSetup(
        username=args.user,
        ssh_key=args.ssh_key,
        ssh_port=args.ssh_port,
        sudo=not args.no_sudo,
        extra_ports=args.extra_ports,
    )

    try:
        setup.run()
    except Exception as e:
        log.error(f'💥 Ошибка: {e}')
        return 1

    return 0
