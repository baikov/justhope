# justhope

Утилита для базового hardening сервера Ubuntu/Debian (создание пользователя, SSH, UFW, fail2ban).

## Установка и запуск одной командой

Первый запуск предполагается **из-под root** (на чистом сервере `sudo` может ещё не быть настроен).

Вариант 1 — запустить прямо из GitHub через `pipx` (ничего не “засоряет” системный Python):

```bash
python3 -m pip install -U pipx
pipx run --spec "git+https://github.com/<owner>/<repo>.git" justhope setup \
  --user deploy \
  --ssh-port 2222 \
  --extra-ports 80 443
```

Вариант 2 — если на сервере есть `uv`, можно сделать то же самое через `uvx`:

```bash
uvx --from "git+https://github.com/<owner>/<repo>.git" justhope setup \
  --user deploy \
  --ssh-port 2222 \
  --extra-ports 80 443
```

Замените `<owner>/<repo>` на ваш репозиторий.

## Установка как команды `justhope`

Если хотите, чтобы команда была установлена на сервере:

```bash
python3 -m pip install "git+https://github.com/<owner>/<repo>.git"
# затем:
justhope setup --user deploy --ssh-key ~/.ssh/id_ed25519.pub --ssh-port 2222
```

## Примечания

- Пароль пользователю не задаётся: предполагается вход по SSH-ключу.
- Скрипт старается не потерять доступ: перед `reload ssh` делает `sshd -t` и при ошибке откатывает конфиг.
- Новый пользователь создаётся в процессе и (опционально) получает sudo-доступ — поэтому первый запуск делайте под root.
- Если `--ssh-key` не задан, ключи копируются из `/root/.ssh/authorized_keys` в `~user/.ssh/authorized_keys`.
- Если `--ssh-key` задан, он должен быть одной строкой публичного ключа (например `ssh-ed25519 AAAA... comment`), и root-ключи не копируются.
