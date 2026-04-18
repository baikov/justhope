# justhope

Утилита для базового hardening сервера Ubuntu/Debian (создание пользователя, SSH, UFW, fail2ban).

## Установка и запуск одной командой

```
apt update && apt upgrade -y && apt install -y git ca-certificates && \
wget -qO- https://astral.sh/uv/install.sh | sh && \
source $HOME/.local/bin/env && \
source $HOME/.bashrc
```

Первый запуск предполагается **из-под root** (на чистом сервере `sudo` может ещё не быть настроен).

## Установка как команды `justhope`

Если хотите, чтобы команда была установлена на сервере:

### Вариант A — через `uv tool` (рекомендуется, если используешь `uv`)

```bash
uv tool install --from "git+https://github.com/baikov/justhope.git" justhope

# затем:
justhope --help
justhope setup --user test --ssh-port 2222
```

Обновление:

```bash
uv tool update justhope
```

### Вариант B — через `venv`

```bash
apt update
apt install -y python3-venv git ca-certificates

python3 -m venv /opt/justhope-venv
/opt/justhope-venv/bin/pip install -U pip
/opt/justhope-venv/bin/pip install "git+https://github.com/baikov/justhope.git"

ln -sf /opt/justhope-venv/bin/justhope /usr/local/bin/justhope

# затем:
justhope setup --user deploy --ssh-key "ssh-ed25519 AAAA... comment" --ssh-port 2222
```

## Обновление

Если `justhope` установлен в `venv` (например, как в примере выше через `/opt/justhope-venv`), можно подтянуть свежие изменения из GitHub командой:

```bash
justhope update
```

По умолчанию команда попробует использовать `uv` (если он установлен), иначе обновит через `pip` в текущем окружении.

Если `justhope` установлен через `uv tool`, обновляй так:

```bash
uv tool update justhope
```

Если запускаешь через `pipx run`, отдельное обновление не нужно — просто запусти команду ещё раз (при необходимости добавь `--pip-args="--no-cache-dir"`).

## Примечания

- Пароль пользователю не задаётся: предполагается вход по SSH-ключу.
- Скрипт старается не потерять доступ: перед `reload ssh` делает `sshd -t` и при ошибке откатывает конфиг.
- Новый пользователь создаётся в процессе и (опционально) получает sudo-доступ — поэтому первый запуск делайте под root.
- Если `--ssh-key` не задан, ключи копируются из `/root/.ssh/authorized_keys` в `~user/.ssh/authorized_keys`.
- Если `--ssh-key` задан, он должен быть одной строкой публичного ключа (например `ssh-ed25519 AAAA... comment`), и root-ключи не копируются.
- По умолчанию скрипт в начале делает `apt update` и `apt upgrade -y`, создаёт swapfile и настраивает окружение пользователя (zsh + oh-my-zsh).
- Если что-то из этого не нужно, смотри `justhope setup --help` (флаги `--no-upgrade`, `--no-swap`, `--no-zsh`, `--no-ohmyzsh`, `--no-base-packages`).
