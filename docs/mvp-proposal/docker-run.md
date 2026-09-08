# Контейнерный контур AutoPostTG

На Mac нужны только уже работающий Docker runtime и Docker Compose.
Python, PostgreSQL, Node и Playwright устанавливаются внутри образов.

## Запуск

Из корня репозитория:

```sh
docker compose up --build -d app
docker compose logs --tail=100 app
```

UI: http://127.0.0.1:8000. PostgreSQL не публикует порт на хосте.
Код `src` подключён только для чтения: Python перезапускается через reload,
изменения HTML/JS/CSS видны при обновлении страницы. Один процесс приложения
содержит один планировщик.
База, медиа и ключ шифрования токенов находятся в отдельных Docker volumes.
При первом запуске приложение выполняет миграции и создаёт свой ключ шифрования.

Необязательные переменные приведены в `deploy/autopost.env.example`.
По умолчанию используются CONTENT_ANALYZER=codex и CONTENT_MODEL=gpt-5.6-terra.
Codex входит в образ; его авторизация сохраняется в volume приложения.
Для Gemini задайте CONTENT_ANALYZER=gemini, доступную вашему проекту CONTENT_MODEL
и GEMINI_API_KEY через локальный игнорируемый `.env`.

Во вкладке «Подключения» редактор задаёт канал и правило публикации.
По умолчанию опоздание не ограничено: после запуска сервис отправляет накопившиеся
принятые посты. Пост требует сохранённого будущего времени
и явного принятия; после изменения плана нужно новое принятие.
`uncertain` автоматически не повторяется.
Telegram читается через сохранённую сессию аккаунта участника группы.

## Вход в Telegram-аккаунт

Для источника, куда нельзя добавить бота, подготовлен вход в аккаунт участника.
В игнорируемом `.env` задаются `TELEGRAM_API_ID` и `TELEGRAM_API_HASH`.
После изменения этих переменных пересоздайте app: `docker compose up -d app`.

На Mac откройте `scripts/connect-telegram.command` двойным щелчком либо выполните:

```sh
docker compose exec app python -m postify.telegram_login --find "часть названия группы"
```

На телефоне: Telegram → Настройки → Устройства → Подключить устройство.
Отсканируйте QR из терминала. Если включена двухэтапная проверка, введите пароль
в терминале (ввод скрыт). Команда покажет только совпадающие группы/каналы и их ID.
Сессия сохраняется в `/data/telegram/account.session` в volume приложения
(каталог 0700, файлы 0600); повторный вход использует её. Одновременный запуск
входа блокируется. Отозвать доступ можно в списке устройств Telegram.

Команда выполняет вход и поиск группы; сама не импортирует и не публикует посты.
Добавьте группу во вкладке «Подключения». Первичная загрузка ограничена
последними 100 сообщениями; затем сохраняется позиция чтения и исключаются дубли.

## Целевые проверки

Тестовый образ содержит снимок кода и тестов. При разработке подключайте текущие
src/tests через bind mount, чтобы не пересобирать образ после каждой правки.
Тестовая БД отдельная, временная; не используйте рабочую БД для pytest.

```sh
docker compose --profile test build test
docker compose --profile test run --rm test python -m pytest -q \
  tests/unit/adapters/ai/test_gemini_content_analyzer.py \
  tests/unit/adapters/sources/test_telegram_group.py \
  tests/unit/adapters/telegram/test_bot_api.py \
  tests/unit/application/content/test_process_content.py \
  tests/unit/application/ingestion/test_import_candidates.py \
  tests/integration/infrastructure/test_mvp_plan_delivery.py \
  tests/integration/infrastructure/test_mvp_source_storage.py \
  tests/integration/test_mvp_pipeline.py \
  tests/integration/test_cleanup_migration.py \
  tests/ui_mockup
```

Фактические результаты проверок записаны в [cleanup-progress.md](cleanup-progress.md).
Тесты подменяют внешние AI/Telegram; они не оценивают качество текстов редактором.

Очистка схемы 20260905_19 необратима через Alembic downgrade: удалённые настройки
восстанавливаются из резервной копии БД вместе с прежним кодом. До обновления
существующей установки сохраните dump и проверьте его восстановление отдельно.

Целевое размещение MVP — облачный VPS. Текущий контур на Mac используется для
разработки и проверки. Перенос требует адреса/SSH-доступа и выбранного способа
доступа редактора. Порт приложения пока привязан к loopback; он доступен через
SSH-туннель. Для публичного домена необходимо отдельно настроить доступ и HTTPS.

Остановить контур с сохранением данных:

```sh
docker compose --profile test down
```
