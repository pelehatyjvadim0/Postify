# Wave 5 — наблюдаемость Telegram MVP

Дата: 2026-08-09.

## Атомарный переход

- `Sₙ`: `main@efe959c` долговечно хранит кандидатов, решения, попытки
  подготовки контента, пакеты и Telegram-доставки, но операторская команда
  `status` показывает только доступность БД, число кандидатов и systemd-состояния.
  Результат планового запуска теряется вне stdout, дефицит трёх публикаций в
  день не объясняется, а сохранённые ошибки и история доставки не видны одной
  командой.
- `Sₙ₊₁`: одна команда `postify status` строит согласованный долговечный снимок
  сущностей и последних запусков, показывает историю Telegram-попыток,
  вычисляет размер и причины дефицита дневного плана и перечисляет безопасные
  эксплуатационные сигналы с идентификаторами затронутых записей.

Переход атомарен: его можно принять по одному сохранённому состоянию PostgreSQL
и одному CLI-отчёту. Будущие UI, форматы и площадки для доказательства не нужны.

## Границы

В Wave 5 входят:

- узкий долговечный журнал запусков `run-once` и `publish-once`;
- read-only проекция состояния уже созданных сущностей;
- последние десять попыток Telegram-доставки;
- объяснение покрытия плана из трёх публикаций на текущий локальный день;
- безопасные сигналы о сохранённых сбоях, незавершённых запусках, cleanup,
  миграциях и systemd;
- расширение существующей команды `status`, миграция и wheel-контракт.

Не входят:

- UI и конфигурация контентных контуров Wave 6;
- новый формат текста, тематики, аудитории, источники или площадки;
- Prometheus, веб-панель, общий metrics/event service, retention и алерты;
- статистика охватов, вовлечённости, стоимости или эффективности контента;
- изменение расписаний, выбора пакета, повторов, подтверждения, cleanup или
  любой другой семантики Telegram-доставки;
- исправление известных несвязанных дефектов и обновление текстового формата.

## Рассмотренные подходы

### 1. Согласованный read-model и узкий журнал запусков — рекомендуется

Существующие таблицы остаются источником истины о сущностях, квотах и доставке.
Добавляется только `operation_runs`, чтобы переживающие перезапуск сведения о
начале и исходе `run-once`/`publish-once` не зависели от journald. Отдельный
application action собирает снимок через узкий query-port, а CLI только
добавляет systemd-пробы и форматирует результат.

Плюсы: закрывает все операторские вопросы, сохраняет фактические причины и не
дублирует доменные сущности. Минус: требуется одна миграция и безопасная
обвязка двух команд.

### 2. Только SQL-проекция существующих таблиц

`status` читает текущие таблицы без новой записи. Это самый малый diff и не
затрагивает write-path, но после падения процесса нельзя отличить «слот не
запускался» от «запуск упал до сохранённого доменного исхода». Требование
долговечного эксплуатационного журнала выполняется не полностью.

### 3. Универсальный append-only журнал событий и агрегаты

Каждый этап пишет обобщённые события с JSON payload, поверх которых строятся
проекции и метрики. Подход расширяем, но создаёт общий event/metrics service,
дублирует уже существующие таблицы и выходит за границу Wave 5.

Решение: подход 1. Он добавляет ровно отсутствующий факт запуска, а остальное
вычисляет из уже подтверждённых долговечных данных.

## Архитектура

### Долговечный write-path

Новый application-компонент наблюдения использует `OperationRunRepository` и
оборачивает оба существующих action одинаковым операционным механизмом:

1. до вызова action создать строку `running` и commit;
2. выполнить исходный action без изменения его входов и переходов;
3. после результата сохранить безопасный outcome и `succeeded`;
4. при исключении попытаться сохранить общий безопасный failure code и
   `failed`, затем повторно поднять исходное исключение.

Общий механизм не знает о Telegram HTTP, выборе кандидатов или доменных
переходах. Исходный `PublishContent` по-прежнему единолично владеет reserve,
отправкой, подтверждением, retry/uncertain и media cleanup. Если финализация
журнала после подтверждённой публикации не удалась, CLI сообщает сбой, но
повтор остаётся безопасным благодаря существующей delivery idempotency. Если
запись failure также не удалась, `running` остаётся видимым сигналом; исходное
исключение не маскируется.

### Read-path

`ShowOperationalStatus` получает часы, часовой пояс, дневную цель `3`, лимиты
контента и `OperationalStatusRepository`. Repository за одну read-only
`REPEATABLE READ` транзакцию возвращает типизированный снимок:

- число кандидатов без решения и решений по status/reason;
- попытки подготовки контента по status;
- пакеты по status и десять последних пакетов (`id`, `status`, `created_at`);
- доставки по status, готовые к claim пакеты и pending cleanup;
- десять последних delivery attempts с package ID, attempt number, outcome,
  безопасным code, временем и `message_id`;
- дневное использование квот и подтверждённые сегодня доставки;
- выбранные кандидаты без первой content attempt;
- последние десять operation runs.

Action валидирует известные статусы, вычисляет дефицит и формирует сигналы.
Repository не принимает продуктовых решений, а CLI не содержит SQL или
правил дефицита. Отдельный общий metrics/dashboard слой не создаётся.

## Долговечная модель

Миграция `20260809_05_add_operation_runs.py` добавляет одну таблицу:

```text
operation_runs
  id              bigint primary key
  operation       run_once | publish_once
  status          running | succeeded | failed
  outcome         nullable safe code
  failure_code    nullable safe code
  started_at      timestamptz not null
  finished_at     timestamptz nullable
```

Инварианты именованными constraints:

- `ck_operation_runs_operation` допускает только два текущих CLI action;
- `ck_operation_runs_status` допускает три состояния;
- `ck_operation_runs_terminal_fields` требует:
  `running` без terminal-полей, `succeeded` с `finished_at` и непустым
  `outcome`, `failed` с `finished_at` и непустым `failure_code`;
- timestamps timezone-aware на границе domain/application;
- обновить можно только собственную `running` строку ровно один раз;
- failure/outcome — фиксированные коды, не exception text, URL, token, chat ID
  или содержимое поста.

Для `run_once` успешный outcome — `completed`. Для `publish_once` сохраняется
существующий безопасный outcome: `empty`, `published`, `cleanup_completed`,
`cleanup_pending`, `retryable`, `failed` или `uncertain`. Failure codes:
`run_once_failed` и `publish_once_failed`. Таблица не хранит счётчики, payload
или метрики: факты созданных сущностей читаются из их собственных таблиц.

Downgrade удаляет только `operation_runs`; Wave 4 delivery schema остаётся
неизменной. Upgrade/downgrade/re-upgrade обязаны сохранять package `1`,
delivery и `message_id=6` в live smoke DB.

## Состояния сущностей

CLI показывает фиксированные группы и нулевые значения, чтобы отсутствие
строки нельзя было принять за отсутствие проверки:

- кандидаты: `total`, `undecided`, решения `selected`/`rejected`, причины
  отклонения по текущей taxonomy;
- content attempts: `processing`, `retry_scheduled`, `failed`,
  `analyzed_not_selected`, `packaged`;
- packages: `processing`, `awaiting_review`, `approved`, `rejected`, `failed`,
  `published`;
- delivery: `ready`, `sending`, `retryable`, `failed`, `uncertain`,
  `published`, `cleanup_pending`.

`delivery.ready` означает `approved` package без delivery либо с delivery
`retryable`, то есть ровно состояние, которое существующий Wave 4 repository
может claim. `approved` с `failed`, `uncertain` или `sending` не считается
готовым. Неизвестный status не замалчивается: он попадает в сигнал
`unknown_persisted_state`, а снимок сохраняет его фактический код и count.

## Дефицит и его taxonomy

Локальный день определяется `POSTIFY_TIMEZONE`. Цель Telegram MVP — три
подтверждённые публикации за день. Покрытие и дефицит:

```text
coverage = published_today + delivery.ready
deficit = max(3 - coverage, 0)
```

При нулевом deficit выводится `none`. При deficit больше нуля action возвращает
все применимые причины в стабильном порядке:

1. `delivery_blocked` — есть `failed`, `uncertain` или незавершённая `sending`;
2. `review_backlog` — есть `awaiting_review`;
3. `package_limit_reached` — дневной лимит пакетов исчерпан;
4. `analysis_limit_reached` — дневной лимит анализов исчерпан;
5. `content_failures` — есть `retry_scheduled`, failed attempt или failed package;
6. `processing_backlog` — есть selected candidate без первой content attempt
   либо активная content attempt/package;
7. `selection_backlog` — есть кандидат без решения;
8. `eligible_source_shortage` — предыдущие причины отсутствуют, а готового
   материала всё ещё недостаточно; рядом показываются counts причин rejected.

Это объяснение текущего выпуска, а не прогноз расписания и не аналитическая
метрика. Один объект может подтверждать несколько ограничений; CLI показывает
их все, не приписывая дефицит одной недоказанной причине.

## Эксплуатационные сигналы

Сигнал содержит фиксированные `severity`, `code`, count и до десяти entity ID;
произвольный текст БД или исключения не печатается.

`critical`:

- `database_unavailable` или `migration_not_at_head`;
- `delivery_uncertain`;
- `unknown_persisted_state`.

`warning`:

- `systemd_probe_failed`, inactive/failed import или publish timer;
- `operation_unfinished`, `operation_failed`;
- `delivery_failed`, `delivery_retryable`, `media_cleanup_pending`;
- `content_attempt_failed`, `content_package_failed`;
- `review_required` для ручного backlog.

Активный one-shot service и `running` operation — нормальное состояние.
`running` без активного соответствующего service обозначается
`operation_unfinished`; это сигнал для проверки, а не автоматический вывод о
падении, потому что команда могла быть запущена вручную.

## Контракт `postify status`

Команда не требует Telegram token/chat ID и не обращается к Telegram. Вывод
имеет фиксированные разделы:

```text
Система
  PostgreSQL: доступна; migrations=head
  import timer: active; последнее=...; следующее=...
  publish timer: active; последнее=...; следующее=...
Сущности
  candidates: total=9; undecided=0; selected=9; rejected=0
  content attempts: ...
  packages: ...
  delivery: ready=0; published=1; ...
Последние пакеты (до 10)
  package=1; status=published; created_at=...
Доставка (последние 10 попыток)
  package=1; attempt=1; outcome=published; finished_at=...; message_id=6
План на 2026-08-09 (Europe/Moscow)
  цель=3; опубликовано=1; готово=0; дефицит=2
  причины: processing_backlog
Последние запуски (до 10)
  ...
Проблемы
  WARNING operation_unfinished: runs=...
```

Даты форматируются как ISO-8601 до секунд с локальным UTC offset; пустое
значение — `—`. Группы и строки сортируются детерминированно. История ограничена
десятью строками, но агрегаты и сигналы учитывают все записи.

Systemd-пробы независимы: ошибка одной unit не скрывает PostgreSQL-снимок.
Сохранённые проблемы не делают сам отчёт ошибочным. Exit code `0`, если полный
DB-снимок построен; `1`, если конфигурация неверна, БД недоступна или schema не
на head. При недоступной БД команда всё равно печатает доступные systemd-факты
и `database_unavailable`, но не выдумывает counts.

## Ошибки и безопасность

- DB snapshot выполняется read-only и не исправляет состояния автоматически.
- Ошибка одного systemd probe нормализуется в `unknown` и safe signal; stderr,
  unit journal и command argv не отражаются в отчёте.
- Ошибка snapshot даёт фиксированное `Не удалось получить состояние Postify`;
  traceback и DSN отсутствуют.
- `status` не печатает source URL, post text, media path, Telegram token/chat
  ID, exception text или Telegram response.
- Запись operation failure никогда не маскирует исходное исключение.
- Сбор наблюдаемости не вызывает retry, delivery claim, cleanup, review или
  иной write-path.

## TDD и приёмка

Sol 5.6 High готовит RED без production-кода: точные domain-типы, журнал
запусков, согласованный repository snapshot, deficit taxonomy, сигналы, CLI,
миграцию и wheel. Для каждого требования фиксируются причина RED и мутация.
Terra Medium делает минимальный GREEN. Свежая Terra High сначала проверяет
тесты и мутации, затем production; цикл продолжается до `0 Critical` и
`0 Important`.

Hermetic gate обязан доказать:

- оба action пишут `running → succeeded|failed`, сохраняют только safe codes и
  не меняют существующие результаты/исключения;
- ошибка terminal journal write не вызывает повтор Telegram и остаётся видна;
- снимок согласован при конкурентной записи и не меняет БД;
- все entity states, неизвестные статусы, limit/queue combinations и восемь
  deficit mutations дают ожидаемый результат;
- последние десять delivery attempts сортируются newest-first, содержат
  package ID и не раскрывают чувствительные поля;
- каждая operational mutation создаёт сигнал, healthy state даёт явное
  `Проблем нет`;
- systemd partial failure не скрывает DB, DB/migration failure даёт partial
  safe output и нужный exit code;
- migration `04 → 05 → 04 → 05`, named constraints и clean wheel проходят.

Полный gate: baseline/non-integration, вся PostgreSQL integration suite через
`../../.env.smoke-real` с `DATABASE_URL` unset, rollback/re-upgrade,
`compileall`, Ruff для `src` и изменённых файлов, `uv lock --check`,
`git diff --check`, wheel и CLI help/status.

Live acceptance выполняется на существующей smoke DB без Telegram-вызова:

1. до upgrade подтвердить package `1`, delivery `published`, одну attempt и
   `message_id=6`, не печатая DSN или credentials;
2. выполнить `04 → 05`, реальный `postify status` и увидеть package `1`,
   `published`, attempt `1`, `message_id=6`, дневной deficit и безопасные
   operational signals;
3. повторным read-only запросом подтвердить, что сам `status` не изменил число
   delivery attempts, `message_id` или состояние package/delivery;
4. downgrade `05 → 04` и повторный upgrade должны сохранить Wave 4 данные;
5. повторный `status` должен дать тот же delivery fact и добавить только
   доказанные operation runs.

До live proof Wave 5 не объявляется принятой. Merge в `main`, повторный gate на
`main`, удаление ветки/worktree и cleanup выполняет корневой оркестратор.

## Оркестрация

Wave 5 выполняется в отдельной ветке от принятого `efe959c`. Sol 5.6 High пишет
только RED/trace/reasons/mutation map/evidence; Terra Medium — минимальный
GREEN; свежая Terra High — независимый test/mutation review, затем code review.
Документы evidence/review/run-004 пишутся лаконично на русском. GitHub push,
merge и удаление worktree не выполняются внутри Wave 5.

## Self-review спецификации

- Placeholder scan: незаполненные и отложенные решения отсутствуют.
- Согласованность: дневная цель, ready predicate, taxonomy, сигналы, CLI и live
  acceptance используют одни определения.
- Scope: одна миграция, один журнал операций и одна read-model возможность;
  UI, analytics service и Telegram semantics не затронуты.
- Неоднозначность снята: заданы поля, инварианты, сортировка, лимиты строк,
  error/exit contract и точная граница live-проверки.
