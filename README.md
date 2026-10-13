# Telethon + FastAPI: анонимный чат

Сервис на [Telethon](https://docs.telethon.dev/) с FastAPI и WebSocket.
Несколько Telegram-аккаунтов работают клиентами бота анонимного чата
([@AnonRuBot](https://t.me/AnonRuBot)), а веб-интерфейс даёт управление:
выбрать аккаунт, начать диалог, закончить диалог и переписываться в реальном
времени. Упакован в Docker для размещения на сервере.

## Как это работает

Бот анонимного чата соединяет двух случайных людей и пересылает сообщения между
ними, поэтому весь диалог физически происходит в одном Telegram-чате с этим
ботом. `AnonChatService` держит состояние диалога и по регулярным выражениям
отличает служебные уведомления бота («собеседник найден», «собеседник вышел») от
реальных сообщений собеседника.

```
idle ──start──> searching ──"собеседник найден"──> chatting
  ^                 │                                  │
  └──── stop ───────┴───────── "собеседник вышел" ──────┘
```

`AccountManager` поднимает отдельный Telethon-клиент и отдельный
`AnonChatService` на каждый аккаунт — диалоги полностью независимы. Сервис
публикует каждое событие подписчикам, поэтому WebSocket-клиенты получают
сообщения сразу, без опроса.

## Структура

```
src/app/
├── cli.py                 # подкоманды serve / login / accounts
├── accounts.py            # менеджер Telethon-клиентов по аккаунтам
├── config.py              # настройки и список аккаунтов
├── client.py              # фабрика TelegramClient
├── logger.py              # цветное логирование
├── static/index.html      # страница чата на WebSocket
├── api/
│   ├── app.py             # create_app + lifespan
│   ├── deps.py            # резолв аккаунта для HTTP и для WebSocket
│   ├── schemas.py         # pydantic-модели запросов, ответов и событий
│   └── routers/
│       ├── accounts.py    # список аккаунтов
│       ├── chat.py        # REST-эндпоинты чата
│       └── ws.py          # WebSocket-канал
├── services/
│   └── anon_chat.py       # состояние диалога, история, публикация событий
└── handlers/
    ├── anon_chat.py       # приём сообщений от бота анонимного чата
    ├── ping.py            # .ping → pong (только в «Избранном»)
    └── echo.py            # .echo <text> (только в «Избранном»)
```

## Настройка аккаунтов

Аккаунты задаются одним из двух способов, `ACCOUNTS_FILE` имеет приоритет:

```bash
cp accounts.example.json accounts.json   # файл со списком аккаунтов
# ACCOUNTS_FILE=accounts.json в .env
```

```json
[
  {"id": "main", "phone": "+70000000000"},
  {"id": "second", "phone": "+70000000001", "anon_bot_username": "@AnonRuBot"}
]
```

Либо инлайном в `.env`: `ACCOUNTS=[{"id":"main"},{"id":"second"}]`.
Если не задано ничего, используется один аккаунт `default`.

Обязателен только `id`; `api_id`, `api_hash` и `anon_bot_username`, если не
указаны у аккаунта, берутся из `.env`, а файл сессии по умолчанию —
`<SESSIONS_DIR>/<id>.session`. Один и тот же `API_ID`/`API_HASH` можно использовать
для всех аккаунтов, а если у каждого аккаунта они свои, `.env` их может не
содержать вовсе. Готовую сессию нужно запускать с тем же `api_id`/`api_hash`, с
которыми она была создана.

## Локальный запуск

```bash
uv sync
cp .env.example .env     # заполнить API_ID и API_HASH
uv run bot login main    # интерактивный вход: номер, код, при наличии — пароль 2FA
uv run bot serve
```

Полезные команды: `uv run bot accounts` — показать статус всех аккаунтов,
`uv run bot --help` — список подкоманд.

## Docker

Интерактивный вход в Telegram невозможен при старте контейнера, поэтому сессии
авторизуются отдельной командой и хранятся в volume:

```bash
cp .env.example .env
cp accounts.example.json accounts.json
docker compose build

# по одному разу на аккаунт, нужен TTY для ввода кода
docker compose run --rm app login main
docker compose run --rm app login second

docker compose up -d
docker compose logs -f
```

Сервис поднимется на `http://<сервер>:8000` (порт меняется через `HOST_PORT`).
Неавторизованные аккаунты не мешают старту: они остаются в списке со статусом
«не авторизован», их эндпоинты отвечают `503`, остальные работают нормально.

Сессии лежат в каталоге `./sessions` рядом с `docker-compose.yml` (bind mount) —
он переживает пересборку образа и обновления. Контейнер пишет в него от UID 1000.

## CI/CD

Workflow `.github/workflows/ci-cd.yml`:

- **lint** — `ruff check` и `ruff format --check` на каждый push и PR;
- **build** — сборка образа; на `main` он публикуется в Docker Hub с тегами `<sha>` и `latest`;
- **deploy** — только для `main`: по SSH копирует на сервер `docker-compose.yml` и
  `deploy/deploy.sh` и запускает скрипт. Он подтягивает образ, перезапускает
  контейнер и ждёт healthcheck (`/health`). Если проверка не прошла — откатывает на
  предыдущий образ, и job падает. Успешно задеплоенный тег записывается в
  `APP_IMAGE` в `.env` сервера.

### Подготовка сервера (один раз)

Нужны Docker и Docker Compose v2.17+. Пользователь деплоя должен входить в группу
`docker`.

```bash
sudo mkdir -p /opt/chat-engine && sudo chown $USER /opt/chat-engine
cd /opt/chat-engine
# положить сюда accounts.json и при необходимости .env (по образцу .env.example);
# готовые сессии — в sessions/<id>.session
mkdir -p sessions && sudo chown -R 1000:1000 sessions
```

После первого успешного деплоя авторизуйте аккаунты (используется образ из `APP_IMAGE`):

```bash
docker compose run --rm app login main
```

### Настройки GitHub

Settings → Secrets and variables → Actions, на уровне репозитория:

| Тип | Имя | Значение |
| --- | --- | --- |
| Variable или Secret | `DOCKERHUB_USERNAME` | логин Docker Hub |
| Variable | `DOCKERHUB_IMAGE` | необязательно, по умолчанию `<DOCKERHUB_USERNAME>/chat-engine` |
| Secret | `DOCKERHUB_TOKEN` | Personal Access Token Docker Hub с правами Read & Write |

Если логин задан секретом, GitHub маскирует его в логах, и имя образа там
отображается как `***`.

Доступ к серверу (на уровне репозитория или окружения `production`):

| Тип | Имя | Значение |
| --- | --- | --- |
| Secret | `DEPLOY_HOST` | адрес сервера |
| Secret | `DEPLOY_USER` | пользователь SSH |
| Secret | `DEPLOY_SSH_KEY` | приватный ключ, публичная часть — в `~/.ssh/authorized_keys` на сервере |
| Secret | `SSH_KNOWN_HOSTS` | необязательно: вывод `ssh-keyscan -p <port> <host>` |
| Variable | `DEPLOY_PATH` | необязательно, по умолчанию `~/chat-engine` |
| Variable | `DEPLOY_PORT` | необязательно, по умолчанию `22` |

Без `SSH_KNOWN_HOSTS` ключ сервера запрашивается при каждом деплое, и подмену
сервера (MITM) обнаружить нельзя. С ним GitHub подключается только к серверу с
известным ключом.

Ключ лучше выпустить отдельный: `ssh-keygen -t ed25519 -f deploy_key -N ""`.
На время деплоя сервер логинится в Docker Hub тем же `DOCKERHUB_TOKEN` (токен
передаётся через stdin), а после деплоя выходит из аккаунта. Так работает и
приватный репозиторий, и нет анонимного лимита на скачивание.

### Откат вручную

```bash
cd /opt/chat-engine
APP_IMAGE=<dockerhub-user>/chat-engine:<старый-sha> bash deploy.sh
```

Для приватного репозитория сначала выполните `docker login`.

## WebSocket

`ws://<сервер>:8000/api/v1/accounts/{account_id}/chat/ws` — основной способ
работы с чатом.

Клиент отправляет команды:

```json
{"action": "start"}
{"action": "stop"}
{"action": "send", "text": "привет"}
```

Сервер сразу после подключения присылает снимок текущего диалога, а дальше —
события по мере их появления:

```json
{"type": "snapshot", "state": "idle", "messages": []}
{"type": "state", "state": "searching", "message": null}
{"type": "message", "state": "chatting", "message": {"seq": 3, "direction": "in", "text": "привет", "at": "..."}}
{"type": "error", "detail": "No partner connected (state=searching)"}
```

`direction` — `in` (от собеседника), `out` (наше) или `system` (служебное
сообщение бота). Благодаря снимку при подключении страницу можно перезагружать
без потери переписки, а при обрыве клиент переподключается сам. Подключение к
неизвестному или неавторизованному аккаунту закрывается с кодом `1008`.

## REST

| Метод и путь | Назначение |
| --- | --- |
| `GET /api/v1/accounts` | Список аккаунтов и их статус |
| `POST /api/v1/accounts/{id}/chat/start` | Начать чат |
| `POST /api/v1/accounts/{id}/chat/stop` | Закончить чат или отменить поиск |
| `POST /api/v1/accounts/{id}/chat/messages` | Отправить сообщение |
| `GET /api/v1/accounts/{id}/chat/messages` | Переписка (`after_seq`, `limit`) |
| `GET /api/v1/accounts/{id}/chat/status` | Состояние и последний `seq` |

Коды ответов: `404` — неизвестный аккаунт, `503` — аккаунт не авторизован,
`409` — действие невозможно в текущем состоянии (отправка без собеседника,
повторный старт). Swagger — на `/docs`.

```bash
curl -X POST localhost:8000/api/v1/accounts/main/chat/start
curl -X POST localhost:8000/api/v1/accounts/main/chat/messages \
  -H 'Content-Type: application/json' -d '{"text":"привет"}'
curl 'localhost:8000/api/v1/accounts/main/chat/messages?after_seq=0'
```

У каждого сообщения есть монотонный `seq`, поэтому REST-клиент может опрашивать
`?after_seq=<последний полученный>` и получать только новое.

## Настройка под конкретного бота

Боты анонимных чатов используют разные команды и тексты уведомлений:

```
ANON_BOT_USERNAME=@AnonRuBot
ANON_SEARCH_COMMAND=/search
ANON_STOP_COMMAND=/stop
```

Шаблоны распознавания (`ANON_PARTNER_FOUND_PATTERN`, `ANON_PARTNER_LEFT_PATTERN`) —
регистронезависимые регулярные выражения, по умолчанию покрывают типовые русские
и английские формулировки. Бот задаётся глобально и может переопределяться для
отдельного аккаунта полем `anon_bot_username`.

## Ограничения

- Один активный диалог на аккаунт: все WebSocket-клиенты, подключённые к одному
  аккаунту, видят один и тот же чат.
- История хранится в памяти процесса (последние `HISTORY_LIMIT` сообщений) и
  теряется при перезапуске; для продакшена её стоит вынести в Redis.
- Приложение однопроцессное: состояние живёт в памяти, поэтому масштабировать
  репликами нельзя без внешнего хранилища.
- API и WebSocket не аутентифицированы — наружу выставлять только за обратным
  прокси с авторизацией и TLS.
- Если бот управляется inline-кнопками, а не текстовыми командами, их нужно
  нажимать через `message.click()` — в шаблоне этого нет.

## Линтер

```bash
uv run ruff check src
uv run ruff format src
```
