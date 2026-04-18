# justhope

Утилита для базового hardening сервера Ubuntu/Debian (создание пользователя, SSH, UFW, fail2ban).

## Установка и запуск одной командой

Первый запуск предполагается **из-под root** (на чистом сервере `sudo` может ещё не быть настроен).

На Debian 12/13 `pip` обычно не даёт ставить пакеты “в систему” (PEP 668: `externally-managed-environment`).
Поэтому для запуска/установки приложения лучше использовать `pipx`/`uvx` или отдельный `venv`.

Вариант 1 — запустить прямо из GitHub через `pipx` (ничего не “засоряет” системный Python):

```bash
apt update
apt install -y pipx git ca-certificates

pipx run --spec "git+https://github.com/baikov/justhope.git" justhope setup \
  --user test \
  --ssh-key "ssh-ed25519 AAAA... comment" \
  --ssh-port 2222 \
  --extra-ports 80 443
```

Вариант 2 — если на сервере есть `uv`, можно сделать то же самое через `uvx`:

```bash
uvx --from "git+https://github.com/baikov/justhope.git" justhope setup \
  --user test \
  --ssh-key "ssh-ed25519 AAAA... comment" \
  --ssh-port 2222 \
  --extra-ports 80 443
```

Замените `<owner>/<repo>` на ваш репозиторий.

## Установка как команды `justhope`

Если хотите, чтобы команда была установлена на сервере:

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

## Примечания

- Пароль пользователю не задаётся: предполагается вход по SSH-ключу.
- Скрипт старается не потерять доступ: перед `reload ssh` делает `sshd -t` и при ошибке откатывает конфиг.
- Новый пользователь создаётся в процессе и (опционально) получает sudo-доступ — поэтому первый запуск делайте под root.
- Если `--ssh-key` не задан, ключи копируются из `/root/.ssh/authorized_keys` в `~user/.ssh/authorized_keys`.
- Если `--ssh-key` задан, он должен быть одной строкой публичного ключа (например `ssh-ed25519 AAAA... comment`), и root-ключи не копируются.
- По умолчанию скрипт в начале делает `apt update` и `apt upgrade -y`, создаёт swapfile и настраивает окружение пользователя (zsh + oh-my-zsh).
- Если что-то из этого не нужно, смотри `justhope setup --help` (флаги `--no-upgrade`, `--no-swap`, `--no-zsh`, `--no-ohmyzsh`, `--no-base-packages`).
