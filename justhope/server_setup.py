"""Базовая настройка (hardening) сервера Ubuntu/Debian."""

from __future__ import annotations

import argparse
import os
import pwd
import re
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
        do_upgrade: bool = True,
        setup_swap: bool = True,
        swap_multiplier: int = 2,
        swap_size_gb: int | None = None,
        install_base_packages: bool = True,
        setup_zsh: bool = True,
        setup_ohmyzsh: bool = True,
    ):
        self.username = username
        self.ssh_key = ssh_key
        self.ssh_port = ssh_port
        self.sudo = sudo
        self.extra_ports = extra_ports or []
        self.home = Path(f'/home/{username}')
        self._ssh_access_ready: bool | None = None

        self.do_upgrade = do_upgrade
        self.setup_swap = setup_swap
        self.swap_multiplier = swap_multiplier
        self.swap_size_gb = swap_size_gb
        self.install_base_packages = install_base_packages
        self.setup_zsh_enabled = setup_zsh
        self.setup_ohmyzsh_enabled = setup_ohmyzsh

    def _run_as_user(self, command: str, check: bool = True) -> subprocess.CompletedProcess:
        return self._run(['runuser', '-l', self.username, '-c', command], check=check)

    def _apt(self, args: Sequence[str], check: bool = True) -> subprocess.CompletedProcess:
        # apt/apt-get могут спрашивать вопросы на upgrade — просим noninteractive.
        return self._run(['env', 'DEBIAN_FRONTEND=noninteractive', *args], check=check)

    def _is_package_installed(self, package: str) -> bool:
        # dpkg-query возвращает 0 и строку вида: "install ok installed" если пакет установлен.
        res = self._run(['dpkg-query', '-W', '-f=${Status}', package], check=False)
        return res.returncode == 0 and 'install ok installed' in (res.stdout or '')

    def apt_update(self) -> None:
        log.info('📦 apt update...')
        self._apt(['apt', 'update'])

    def apt_upgrade(self) -> None:
        log.info('📦 apt upgrade -y...')
        self._apt(['apt', 'upgrade', '-y'])

    def _mem_total_kb(self) -> int:
        meminfo = Path('/proc/meminfo').read_text(encoding='utf-8', errors='replace')
        m = re.search(r'^MemTotal:\s+(\d+)\s+kB\s*$', meminfo, flags=re.MULTILINE)
        if not m:
            msg = 'Не смог прочитать MemTotal из /proc/meminfo'
            raise RuntimeError(msg)
        return int(m.group(1))

    def setup_swapfile(self) -> None:
        if not self.setup_swap:
            return

        swapfile = Path('/swapfile')

        swaps = self._run(['swapon', '--show', '--noheadings'], check=False)
        if (swaps.stdout or '').strip() and not swapfile.exists():
            log.info('✓ Swap уже настроен (есть активные swap-устройства). Пропускаю создание swapfile.')
            return

        if swapfile.exists():
            # Если файл существует, попробуем убедиться, что он активен и есть в fstab.
            active = '/swapfile' in (swaps.stdout or '')
            if not active:
                self._run(['chmod', '600', str(swapfile)])
                self._run(['mkswap', str(swapfile)], check=False)
                self._run(['swapon', str(swapfile)], check=False)
        else:
            if self.swap_size_gb is not None:
                size_bytes = int(self.swap_size_gb) * 1024 * 1024 * 1024
            else:
                size_bytes = self._mem_total_kb() * 1024 * max(1, int(self.swap_multiplier))

            size_mb = max(128, (size_bytes + (1024 * 1024 - 1)) // (1024 * 1024))
            log.info(f'💾 Создаю swapfile /swapfile размером ~{size_mb} MiB')

            fallocate = shutil.which('fallocate')
            if fallocate:
                self._run([fallocate, '-l', f'{size_mb}M', str(swapfile)])
            else:
                self._run(['dd', 'if=/dev/zero', f'of={swapfile}', 'bs=1M', f'count={size_mb}'])

            self._run(['chmod', '600', str(swapfile)])
            self._run(['mkswap', str(swapfile)])
            self._run(['swapon', str(swapfile)])

        fstab = Path('/etc/fstab')
        entry = '/swapfile none swap sw 0 0'
        fstab_text = fstab.read_text(encoding='utf-8', errors='replace') if fstab.exists() else ''
        if entry not in fstab_text:
            with fstab.open('a', encoding='utf-8') as f:
                if fstab_text and not fstab_text.endswith('\n'):
                    f.write('\n')
                f.write(entry + '\n')
        log.info('✓ Swap настроен')

    def install_packages(self, packages: Sequence[str]) -> None:
        if not packages:
            return
        for package in packages:
            if self._is_package_installed(package):
                log.info(f'✓ Пакет уже установлен: {package}')
                continue
            log.info(f'📦 Ставим пакет: {package}...')
            self._apt(['apt', 'install', '-y', package])
            log.info(f'✓ Установлен успешно: {package}')

    def _ensure_visudo(self) -> str:
        visudo_bin = shutil.which('visudo')
        if visudo_bin is not None:
            return visudo_bin

        log.info('ℹ️  visudo не найден — устанавливаю пакет sudo...')
        self.install_packages(['sudo'])
        visudo_bin = shutil.which('visudo')
        if visudo_bin is None:
            msg = 'Не найден visudo даже после установки sudo'
            raise RuntimeError(msg)
        return visudo_bin

    def setup_base_packages(self) -> None:
        if not self.install_base_packages:
            return
        log.info('🧰 Устанавливаю базовые пакеты...')
        packages = [
            'neovim',
            'tmux',
            'htop',
            'git',
            'curl',
            'wget',
            'zip',
            'unzip',
            'build-essential',
            'ca-certificates',
            'gnupg',
            'lsb-release',
        ]
        self.install_packages(packages)
        log.info('✓ Базовые пакеты установлены')

    def setup_zsh(self) -> None:
        if not self.setup_zsh_enabled:
            return
        log.info('🐚 Устанавливаю zsh и ставлю shell по умолчанию...')

        self.install_packages(['zsh'])
        zsh_path = shutil.which('zsh') or '/usr/bin/zsh'

        try:
            current_shell = pwd.getpwnam(self.username).pw_shell
        except KeyError:
            current_shell = ''

        if current_shell != zsh_path:
            self._run(['chsh', '-s', zsh_path, self.username])

        log.info('✓ zsh настроен')

    def setup_oh_my_zsh(self) -> None:
        if not self.setup_ohmyzsh_enabled:
            return
        log.info('✨ Устанавливаю oh-my-zsh и плагины...')

        # Требуется git + curl
        self.install_packages(['git', 'curl'])

        ohmyzsh_dir = self.home / '.oh-my-zsh'
        if not ohmyzsh_dir.exists():
            install_cmd = (
                'RUNZSH=no CHSH=no KEEP_ZSHRC=yes '
                'sh -c "$(curl -fsSL https://raw.githubusercontent.com/ohmyzsh/ohmyzsh/master/tools/install.sh)"'
            )
            self._run_as_user(install_cmd)

        plugins_dir = ohmyzsh_dir / 'custom' / 'plugins'
        autosug = plugins_dir / 'zsh-autosuggestions'
        syntaxhl = plugins_dir / 'zsh-syntax-highlighting'

        if not autosug.exists():
            self._run_as_user(
                'mkdir -p ~/.oh-my-zsh/custom/plugins && '
                'git clone --depth=1 https://github.com/zsh-users/zsh-autosuggestions '
                '~/.oh-my-zsh/custom/plugins/zsh-autosuggestions'
            )

        if not syntaxhl.exists():
            self._run_as_user(
                'mkdir -p ~/.oh-my-zsh/custom/plugins && '
                'git clone --depth=1 https://github.com/zsh-users/zsh-syntax-highlighting '
                '~/.oh-my-zsh/custom/plugins/zsh-syntax-highlighting'
            )

        zshrc = self.home / '.zshrc'
        if zshrc.exists():
            text = zshrc.read_text(encoding='utf-8', errors='replace')
        else:
            text = ''

        desired_plugins = ['git', 'zsh-autosuggestions', 'zsh-syntax-highlighting']

        m = re.search(r'^plugins=\(([^)]*)\)\s*$', text, flags=re.MULTILINE)
        if m:
            current = [p for p in m.group(1).split() if p.strip()]
            merged: list[str] = []
            for p in current + desired_plugins:
                if p not in merged:
                    merged.append(p)
            new_line = 'plugins=(' + ' '.join(merged) + ')'
            text = re.sub(r'^plugins=\(([^)]*)\)\s*$', new_line, text, flags=re.MULTILINE)
        else:
            if text and not text.endswith('\n'):
                text += '\n'
            text += 'plugins=(' + ' '.join(desired_plugins) + ')\n'

        zshrc.write_text(text, encoding='utf-8')
        self._run(['chown', f'{self.username}:{self.username}', str(zshrc)])
        log.info('✓ oh-my-zsh настроен')

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

        visudo_bin = self._ensure_visudo()

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
            try:
                self._run([visudo_bin, '-c', '-f', str(tmp)])
            except FileNotFoundError:
                # На некоторых минимальных образах sudo/visudo может отсутствовать — попробуем поставить и повторить.
                visudo_bin = self._ensure_visudo()
                self._run([visudo_bin, '-c', '-f', str(tmp)])
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

        # Сначала — обновление системы и базовые вещи.
        self.apt_update()
        if self.do_upgrade:
            self.apt_upgrade()

        self.setup_swapfile()
        self.setup_base_packages()

        self.create_user()

        if not self.ensure_ssh_access():
            log.error(
                '❌ Не найден SSH-ключ для нового пользователя. '
                'Укажи `--ssh-key "ssh-ed25519 AAAA..."` или добавь ключ в /root/.ssh/authorized_keys, '
                'после чего запусти команду ещё раз. '
                'Останавливаюсь до изменений SSH/UFW, чтобы не отрезать доступ.'
            )
            return

        self.setup_sudo()

        # Шаги, которые обычно делают уже под новым пользователем.
        self.setup_zsh()
        self.setup_oh_my_zsh()

        self.setup_ssh()
        self.setup_ufw(allow_ports=[self.ssh_port, *self.extra_ports])
        self.setup_fail2ban()

        log.info('✅ Готово! Проверь подключение под новым юзером:')
        log.info(f'   ssh -p {self.ssh_port} {self.username}@<server_ip>')
        log.info('⚠️  Не закрывай текущую сессию root, пока не убедишься, что новый логин работает!')


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    return build_parser().parse_args(argv)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog='justhope setup', description='Base server hardening (Ubuntu/Debian)')
    parser.add_argument('--user', default='user', help='Имя нового пользователя (по умолчанию: user)')
    parser.add_argument(
        '--ssh-key',
        help='Публичный SSH-ключ одной строкой (опционально). Если не задан, берём ключи из /root/.ssh/authorized_keys',
    )
    parser.add_argument('--ssh-port', type=int, default=22, help='Порт SSH (по умолчанию 22)')
    parser.add_argument('--no-sudo', action='store_true', help='Не добавлять в sudo')
    parser.add_argument('--extra-ports', nargs='+', type=int, default=[], help='Доп. порты для UFW (например, 80 443)')

    parser.add_argument(
        '--no-upgrade',
        action='store_true',
        help='Не выполнять apt upgrade (apt update всё равно будет)',
    )

    parser.add_argument('--no-swap', action='store_true', help='Не создавать swapfile')
    parser.add_argument('--swap-multiplier', type=int, default=2, help='Swap = RAM * multiplier (по умолчанию 2)')
    parser.add_argument('--swap-size-gb', type=int, help='Явный размер swap в GiB (перебивает multiplier)')

    parser.add_argument('--no-base-packages', action='store_true', help='Не ставить базовые пакеты (neovim, tmux, ...)')
    parser.add_argument('--no-zsh', action='store_true', help='Не ставить zsh и не менять shell')
    parser.add_argument('--no-ohmyzsh', action='store_true', help='Не ставить oh-my-zsh и плагины')

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = parse_args(argv)
    except SystemExit as e:
        # argparse использует SystemExit для --help и ошибок парсинга.
        return int(e.code or 0)

    if os.geteuid() != 0:
        log.error('❌ Запускай от root, дружище. justhope setup --user <name> ...')
        return 1

    setup = ServerSetup(
        username=args.user,
        ssh_key=args.ssh_key,
        ssh_port=args.ssh_port,
        sudo=not args.no_sudo,
        extra_ports=args.extra_ports,
        do_upgrade=not args.no_upgrade,
        setup_swap=not args.no_swap,
        swap_multiplier=args.swap_multiplier,
        swap_size_gb=args.swap_size_gb,
        install_base_packages=not args.no_base_packages,
        setup_zsh=not args.no_zsh,
        setup_ohmyzsh=not args.no_ohmyzsh,
    )

    try:
        setup.run()
    except Exception as e:
        log.error(f'💥 Ошибка: {e}')
        return 1

    return 0
