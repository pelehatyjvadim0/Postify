# Postify

Первая волна Postify импортирует кандидатов из Hacker News Algolia в PostgreSQL. Импорт идемпотентен: повторный `run-once` не создаёт дубликаты.

## Что готово

- конфигурация из `.env` и переменных окружения;
- импорт кандидатов из HN Algolia;
- PostgreSQL-хранилище и Alembic-миграции;
- команды `run-once`, `start`, `status`, `stop`;
- systemd service и timer для запуска импорта по расписанию.

Отбор кандидатов, генерация контента, публикация в Telegram и расширенная наблюдаемость ещё не реализованы.

## Подготовка

Нужны Python 3.12+, `uv` и отдельный экземпляр PostgreSQL 16 для Postify. Не используйте общий экземпляр PostgreSQL, если команда `postify stop` не должна иметь право его останавливать.

```sh
uv sync --all-groups
test -e .env || cp .env.example .env
```

Заполните в `.env` безопасные для вашей установки значения как минимум для `DATABASE_URL`, `HN_QUERY`, `POSTGRESQL_SYSTEMD_UNIT`, `POSTGRESQL_OWNERSHIP`, `POSTIFY_ON_CALENDAR` и `POSTIFY_TIMEZONE`. Не добавляйте `.env` в Git.

Примените миграции к той же отдельной базе PostgreSQL 16:

```sh
POSTIFY_ALEMBIC_DATABASE_URL='postgresql+psycopg://<пользователь>:<пароль>@<хост>:5432/<база>' \
  uv run --env-file .env alembic upgrade head
```

`POSTIFY_ALEMBIC_DATABASE_URL` передаётся Alembic явно; команда не берёт URL миграций из другого источника.

## Запуск

Однократный импорт:

```sh
uv run --env-file .env postify run-once
```

Управление настроенным PostgreSQL-unit и планировщиком:

```sh
uv run --env-file .env postify start
uv run --env-file .env postify status
uv run --env-file .env postify stop
```

`start` ждёт доступности базы и проверяет, что миграции находятся на Alembic head, прежде чем включить timer. `stop` сначала отключает timer и ждёт завершения текущего запуска.

## Установка systemd units

Скрипт устанавливает system units. Замените значения в угловых скобках абсолютными путями и данными системного пользователя; для `/etc/systemd/system` нужны соответствующие права.

```sh
sh scripts/install-systemd.sh \
  --project-dir /абсолютный/путь/Postify \
  --env-file /абсолютный/путь/Postify/.env \
  --python /абсолютный/путь/Postify/.venv/bin/python \
  --user <системный-пользователь> \
  --group <системная-группа> \
  --timezone Europe/Moscow \
  --destination /etc/systemd/system \
  --on-calendar 'Mon..Fri *-*-* 09:00:00' \
  --on-calendar 'Mon..Fri *-*-* 14:00:00' \
  --on-calendar 'Mon..Fri *-*-* 19:00:00'
```

Скрипт проверяет расписание и сгенерированные units до установки; он не читает и не исполняет содержимое `.env`.
