# Контекст и итоги Wave 1

## 1. Текущее состояние репозитория

- Рабочая ветка: `feature/postify-waves`.
- Текущий commit: `e66acb5 Восстановил описание и roadmap Postify`.
- Ветка `main` остаётся на `9073276`; Wave 1 в неё не влита.
- В GitHub ничего не отправлялось.
- Wave 2 не начата: отдельный planning-agent был прерван до изменений и коммитов.

## 2. Результат Wave 1

Реализован технический контур `HN Algolia → Candidate → PostgreSQL` и управление короткой задачей через CLI/systemd.

### 2.1. Окружение и конфигурация

- Python 3.12 и зависимости управляются через `uv`.
- Добавлены `pyproject.toml`, `uv.lock` и `.env.example` без рабочих секретов.
- `Settings` валидирует PostgreSQL URL, параметры HN, расписание, ownership PostgreSQL-unit и таймауты.
- Параметры HN-запроса приходят из конфигурации; ниша `AI` не зашита в адаптер.

### 2.2. Домен и импорт

- Добавлена модель `Candidate` с проверкой обязательных полей, абсолютного HTTP(S) URL и timezone-aware времени.
- `raw_payload` хранится независимой глубокой копией и остаётся совместимым с JSONB.
- Добавлены минимальные порты источника и репозитория.
- Реализован сценарий `ImportCandidates` с точным результатом `received/created/duplicates`.
- Реализован адаптер HN Algolia на HTTPX:
  - конфигурируемые query/tags/limit;
  - fallback-поля HN;
  - нормализация времени в UTC;
  - пропуск невалидных hit;
  - нормализованные transport, HTTP, timeout и JSON-ошибки.

### 2.3. PostgreSQL и Alembic

- Добавлена таблица `candidates` с JSONB и именованным unique constraint `(source_name, source_id)`.
- Репозиторий использует PostgreSQL `ON CONFLICT DO NOTHING ... RETURNING`.
- Повторный, batch- и конкурентный импорт не создают дубли.
- Транзакция фиксируется внутри `save_new`; при ошибке выполняется явный rollback.
- Миграции имеют один источник: `src/postify/infrastructure/database/migrations/`.
- Миграции входят в wheel и доступны вне checkout через package resources.
- Root `alembic.ini` используется как dev-конфигурация и указывает на тот же migration tree.

### 2.4. CLI и lifecycle

Добавлены команды:

- `postify run-once` — импортирует и печатает счётчики;
- `postify start` — запускает настроенный PostgreSQL-unit, ждёт БД, проверяет Alembic head и только затем включает timer;
- `postify status` — показывает PostgreSQL, БД, timer, run-once service и число кандидатов;
- `postify stop` — отключает timer, ждёт текущую задачу и затем останавливает PostgreSQL-unit.

Ошибки источника, БД, Alembic и systemd завершают CLI ненулевым кодом и не выводят traceback пользователю.

### 2.5. systemd и installer

- Добавлены oneshot service и timer.
- Installer работает с абсолютными путями и system units.
- Перед установкой выполняется проверка расписания и unit-файлов.
- `.env` не исполняется через shell.
- При сбое копирования, сигнале или ошибке `daemon-reload` восстанавливается предыдущая пара unit-файлов.
- `systemctl is-active` корректно различает terminal state и инфраструктурную ошибку.

### 2.6. Документация

- README сохраняет продуктовое описание, архитектурные принципы и roadmap Waves 1–5.
- Добавлена инструкция установки, миграций, `run-once`, `start/status/stop` и systemd.
- Статус честно отмечает: импорт готов; отбор, генерация и Telegram ещё не реализованы.

## 3. Проверка качества

Свежая проверка на commit `e66acb5` выполнена 2026-08-02 на отдельной user-level PostgreSQL 16:

```text
TEST_DATABASE_URL=<временная PostgreSQL 16> uv run pytest -v
→ 86 passed

uv run python -m compileall -q src
→ exit 0

git diff --check
→ exit 0
```

Финальный Terra 5.6 high reviewer сначала проверил тесты 14 обратными мутациями, затем код. Все мутации дали RED:

1. отключение whitespace validation;
2. shallow copy `raw_payload`;
3. удаление `raise_for_status`;
4. hardcoded HN query;
5. потеря кандидата между source и repository;
6. неверный created count;
7. удаление conflict handling;
8. отсутствие commit;
9. отсутствие rollback;
10. неверная обработка terminal state systemd;
11. отключение rollback installer;
12. timer до readiness/migrations;
13. PostgreSQL stop до ожидания run-once;
14. потеря Alembic package assets/CWD portability.

После scoped re-review открытых Critical/Important замечаний нет.

## 4. Причины возвратов в fix-loop

### 4.1. Preflight: слабые места исходной спецификации

До реализации были исправлены:

- `start/status/stop` не описывали полный порядок PostgreSQL, БД, миграций и timer;
- HN query `AI` был захардкожен;
- интеграционные тесты разрешалось пропускать через `skip`;
- не были определены system/user unit, абсолютные пути, ownership БД и поведение активной задачи;
- TDD RED мог падать из-за отсутствующих зависимостей, а не из-за отсутствующего поведения;
- не было component-теста `MockTransport → HN → PostgreSQL`;
- не были закреплены mutation gates и отдельный Terra-reviewer.

Это был дефект спецификации. Его устранили до первого production-кода.

### 4.2. HN adapter: тест маскировал отсутствие HTTP-проверки

**Возврат:** удаление `raise_for_status()` не делало тест красным, потому что fixture 429/500 имела пустое тело и падала позже при JSON-разборе.

**Причина:** дефект теста исполнителя, не спецификации.

**Исправление:** статусные ответы получили валидный JSON; тест проверяет `SourceFetchError` с `HTTPStatusError` в `__cause__`.

### 4.3. PostgreSQL: формальная конкуренция и слабый rollback-тест

**Возврат 1:** ThreadPoolExecutor не гарантировал реальное пересечение INSERT.

**Возврат 2:** rollback проверялся следующей операцией в новой session и мог быть зелёным без явного rollback.

**Причина:** дефект тестового дизайна исполнителя.

**Исправление:** barrier непосредственно перед INSERT; повторное использование той же session и наблюдение rollback boundary.

### 4.4. systemd installer и controller

Возвраты:

- `is-active` не различал ожидаемый nonzero для `inactive/failed` и реальную ошибку systemctl;
- незаменённый placeholder расписания мог пройти;
- установка двух unit-файлов была неатомарной;
- signal trap мог завершиться с кодом 0 и не откатить первый файл;
- ошибка `daemon-reload` оставляла новые unit-файлы без рабочего reload.

**Причина:** преимущественно дефекты реализации исполнителя на сложной OS-границе. Исходная спецификация была недостаточно точной, но усиленный brief уже требовал ошибки systemctl, rollback и безопасную установку.

### 4.5. CLI, lifecycle и Alembic portability

Возвраты:

- Alembic зависел от текущего каталога;
- `status` печатал фиктивный `run-once: unavailable`;
- engine не закрывался при ошибке конструктора HTTPX client;
- первый CWD-fix работал в editable checkout, но wheel не содержал migration assets.

**Причина:** смешанная.

- CWD, fake status и lifecycle — дефекты реализации исполнителя.
- Wheel packaging — пробел спецификации и интеграционного плана: переносимость установленного пакета не была описана явно до reviewer smoke-теста.

**Исправление:** package-owned migrations, `importlib.resources`, wheel/venv/`/tmp` smoke-test, реальный run-once state и cleanup до `yield`.

### 4.6. README

**Возврат:** завершающий агент заменил README короткой инструкцией и удалил утверждённое продуктовое описание и roadmap.

**Причина:** нарушение scope исполнителем. Задача разрешала дополнить README, а не удалять продуктовый контекст.

**Исправление:** продуктовые разделы восстановлены; операционная инструкция сохранена; scoped re-review чист.

### 4.7. Оркестрационные сбои агентов

- Первый агент неверно понял запрет внешней сети как запрет `uv` загружать зависимости; после уточнения продолжил.
- Встроенный `task-brief` не распознал русские заголовки `Задача N`; briefs создавались вручную.
- Два README-only агента зависли до первого изменения; после двух неудачных попыток оркестратор внёс небольшую документационную правку напрямую и передал её Terra на re-review.
- Planning-agent Wave 2 был прерван до изменений из-за запроса на фиксацию контекста.

## 5. Главный bottleneck

Главный bottleneck Wave 1 — не доменная архитектура и не HN mapping. Основное время заняли внешние границы и доказательство их поведения:

1. PostgreSQL concurrency/transaction semantics;
2. systemd exit codes, signals и атомарный installer;
3. lifecycle ресурсов при ошибках до `yield`;
4. Alembic portability между checkout и wheel;
5. тесты, которые должны краснеть именно от неправильной логики.

### Итог по источнику проблем

| Область | Основной источник |
| --- | --- |
| Preflight требований | Слабая исходная спецификация |
| HN HTTP-тест | Исполнитель / тестовый дизайн |
| PostgreSQL concurrency и rollback | Исполнитель / тестовый дизайн |
| systemd edge cases | Преимущественно исполнитель, частично недостаточная детализация спеки |
| CLI status и lifecycle | Исполнитель |
| Wheel/Alembic assets | Пробел спецификации + интеграционная ошибка исполнителя |
| README regression | Исполнитель |

После усиления preflight-спеки большинство fix-loop возвратов были вызваны не новой архитектурной неопределённостью, а неполной реализацией или тестами, которые первоначально не доказывали заявленное поведение.

## 6. Что не проверено на реальной машине

- System units не устанавливались в `/etc/systemd/system`, потому что работа велась без sudo.
- Настоящий `systemctl` и journal не запускались; они проверены через fake boundary и shell e2e во временных каталогах.
- Настоящий HN API не вызывался в тестах; использовался `httpx.MockTransport`.
- Рабочая PostgreSQL, `.env`, PostgreSQL-unit и расписание пользователя не настроены.
- Wave 1 ещё не влита в `main` и не отправлена в GitHub.

## 7. Точка продолжения

1. Не повторять Wave 1: её рабочий HEAD — `feature/postify-waves@e66acb5`.
2. Перед Wave 2 создать и отдельно проверить spec/plan `selection + decision journal`.
3. Wave 2 начинать только после фиксации точных создаваемых/изменяемых файлов и mutation gates.
4. Сохранять консервативное правило: сомнительный title-only кандидат уходит в резерв, а не получает ложный reject.
5. После Wave 2 снова использовать свежую Terra 5.6 high: сначала тесты/мутации, затем код.
