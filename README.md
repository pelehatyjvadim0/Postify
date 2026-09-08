# AutoPostTG

AutoPostTG — веб-приложение для подготовки и публикации постов в Telegram с
обязательной проверкой редактором.

## Цель и задачи

Цель проекта — сократить ручную работу контент-команды, сохранив контроль над
темой, текстом, временем и каналом публикации.

Система:

- получает сообщения из подключённых Telegram-групп и исключает дубли;
- готовит текст через Codex или Gemini по настройкам проекта;
- передаёт публикацию редактору на проверку и планирование;
- отправляет одобренный пост в выбранный Telegram-канал;
- показывает материалы, очередь, календарь, ошибки и историю действий.

Изменение запланированного поста требует повторного одобрения. Отправка с
неопределённым результатом (`uncertain`) автоматически не повторяется.

## Установка

Поддерживаются macOS, Ubuntu и Debian. На macOS нужен Homebrew либо уже
установленный Docker Desktop. На Linux достаточно доступа root/sudo. Python,
Node.js и PostgreSQL отдельно устанавливать не нужно.

```bash
git clone https://git.keine-media.com/sorrow9/autoposttg.git
cd autoposttg
./install.sh
```

Скрипт установит или запустит Docker, создаст локальный `.env`, соберёт
контейнеры и проверит доступность приложения.

После установки откройте [http://localhost:8000](http://localhost:8000).
Порт доступен только с текущего компьютера.

## Сервер для стабильной работы

Для одного экземпляра AutoPostTG рекомендуется VPS со следующими ресурсами:

| Ресурс | Минимум для проверки | Рекомендуется для работы |
| --- | --- | --- |
| CPU | 2 vCPU | 4 vCPU |
| RAM | 4 ГБ | 8 ГБ |
| Диск | 20 ГБ SSD | 40 ГБ SSD |
| ОС | Ubuntu 22.04/24.04 или Debian 12 | Ubuntu 24.04 LTS |

Рекомендуемая конфигурация учитывает PostgreSQL, сборку Docker-образа, медиа и
запас для обновлений. Использование CPU и RAM под нагрузкой не измерялось;
нагрузочное тестирование не проводилось. Требуемый диск растёт вместе с числом
сохранённых медиафайлов.

Серверу нужен исходящий HTTPS-доступ к Telegram, выбранному AI-провайдеру,
источникам контента и реестрам Docker. UI привязан к `127.0.0.1` и не открыт в
интернет. Для доступа с рабочего компьютера используйте SSH-туннель:

```bash
ssh -L 8000:127.0.0.1:8000 user@server
```

После подключения откройте [http://localhost:8000](http://localhost:8000).

Чтобы открыть UI с обязательным входом по паролю, задайте в `.env`:

```dotenv
AUTOPOST_BIND=0.0.0.0
POSTIFY_ACCESS_PASSWORD=случайный-пароль
POSTIFY_TRUSTED_HOSTS=IP-или-домен-сервера,127.0.0.1,localhost
```

После `docker compose up -d app` интерфейс будет доступен на порту `8000`.
Успешный вход сохраняется в HTTP-only cookie браузера на один год.

## Первичная настройка

### 1. Подключите AI

По умолчанию используется Codex. Авторизация сохраняется в Docker volume:

```bash
docker compose exec app codex login --device-auth
```

Для Gemini укажите в `.env`:

```dotenv
CONTENT_ANALYZER=gemini
CONTENT_MODEL=имя-модели
GEMINI_API_KEY=ключ
```

После изменения `.env` пересоздайте приложение:

```bash
docker compose up -d app
```

### 2. Подключите источник Telegram

Создайте `API ID` и `API Hash` для своего Telegram-аккаунта и добавьте их в
`.env`:

```dotenv
TELEGRAM_API_ID=123456
TELEGRAM_API_HASH=значение
```

Пересоздайте контейнер и войдите в аккаунт по QR-коду:

```bash
docker compose up -d app
docker compose exec app python -m postify.telegram_login
```

На телефоне откройте `Telegram → Настройки → Устройства → Подключить
устройство` и отсканируйте QR-код. Сессия хранится в приватном Docker volume.

### 3. Настройте публикацию

В разделе `Подключения` добавьте Telegram-группу как источник, бота и канал как
получателя, затем создайте маршрут публикации. Остальные параметры проекта и
расписание задаются в интерфейсе.

## Стек

| Компонент | Технологии | Назначение |
| --- | --- | --- |
| Backend | Python 3.12, FastAPI, Uvicorn | API, UI и планировщик |
| Хранилище | PostgreSQL 17, SQLAlchemy, Alembic | Данные и миграции |
| Telegram | Telethon, Telegram Bot API | Чтение источников и публикация |
| AI | Codex CLI, Gemini API | Подготовка текста |
| Frontend | HTML, CSS, JavaScript | Панель редактора |
| Инфраструктура | Docker, Docker Compose, uv | Сборка и запуск |

## Архитектура

```text
Telegram-группа -> импорт -> AI -> проверка редактором -> очередь -> Telegram-канал
                                  |
                              Web-интерфейс
```

Один процесс приложения обслуживает UI и планировщик. PostgreSQL не публикует
порт на хосте. База, медиа, ключ шифрования и Telegram-сессия сохраняются в
Docker volumes.

## Управление

Состояние и логи:

```bash
docker compose ps
docker compose logs -f app
```

Перезапуск и остановка:

```bash
docker compose restart app
docker compose down
```

`docker compose down` сохраняет данные. Команда `docker compose down -v`
удалит базу, медиа, ключ шифрования, AI-авторизацию и Telegram-сессию.

## Разработка

Код из `src/` подключён в контейнер с hot reload. Обычные изменения Python,
HTML, CSS и JavaScript не требуют пересборки образа.

Целевые проверки и технические детали:

- [Запуск в Docker](docs/mvp-proposal/docker-run.md)
- [Проверки MVP](docs/mvp-proposal/verification.md)
- [Результаты очистки](docs/mvp-proposal/cleanup-progress.md)

Тесты запускаются в отдельной временной базе:

```bash
docker compose --profile test build test
docker compose --profile test run --rm test
```

Технический Python namespace пока называется `postify`.
