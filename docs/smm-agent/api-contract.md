# Контракт API

Зафиксирован до начала работ, чтобы фронтенд и бэкенд разрабатывались
параллельно разными инстансами. Изменения контракта — только согласованной
правкой этого файла с уведомлением обеих сторон.

Контекст задачи: [trace.md](trace.md).

---

## 1. Общие правила

- База: `/api`. Ответы `application/json; charset=utf-8`.
- Даты — строки ISO 8601 с таймзоной: `2026-10-09T18:00:00+03:00`.
  Сервер хранит в UTC, отдаёт в таймзоне проекта.
- Идентификаторы — целые положительные числа.
- Тексты — UTF-8 без ограничения на язык.

### Аутентификация

- Сессия в httpOnly cookie, ставится ответом `GET /api/auth/login/status`
  в момент подтверждения входа в Telegram. Cookie `HttpOnly; SameSite=Strict;
  Secure` на https, срок 365 дней.
- Мутирующие методы (`POST`, `PUT`, `PATCH`, `DELETE`) требуют заголовок
  `x-postify-csrf` со значением, выданным при входе, и совпадения Origin.
  Механизм уже есть в `web/security.py` и сохраняется.
- Без действительной сессии любой эндпоинт кроме `/api/auth/*` отвечает `401`.
- `POST /api/auth/login` и `GET /api/auth/login/status` сессии не требуют, но
  проверяют Origin.

### Изоляция данных

Проект принадлежит одному пользователю. Обращение к чужому `project_id`
возвращает **`404`**, а не `403` — существование чужих проектов не
раскрывается. То же для вложенных ресурсов: слотов, постов, изображений.

### Формат ошибки

```json
{ "error": { "code": "slot_topic_required", "message": "Тема слота не заполнена" } }
```

`code` — машиночитаемый, стабильный. `message` — по-русски, показывается
пользователю. Коды валидации полей дополняются полем `field`.

Статусы: `400` невалидный запрос, `401` не авторизован, `404` нет объекта либо
чужой объект, `409` конфликт состояния, `413` файл слишком велик,
`422` не прошла схема, `429` лимит провайдера, `500` внутренняя ошибка.

### Длительные операции

Всё, что требует обращения к модели, отвечает `202` и ссылкой на операцию:

```json
{ "operation_id": 1841, "status": "running" }
```

Фронтенд опрашивает `GET /api/projects/{project_id}/operations/{operation_id}`
до `succeeded` или `failed`. Рекомендуемый интервал — 2 секунды.

```json
{ "operation_id": 1841, "status": "succeeded",
  "result": { "post_id": 77 }, "error": null,
  "started_at": "...", "finished_at": "..." }
```

`status`: `running` | `succeeded` | `failed`.

---

## 2. Перечисления

### Статус слота контент-плана

Единственный источник состояния для календаря.

| Значение | Смысл | В мокапе |
|---|---|---|
| `no_topic` | слот стоит в плане, тема не заполнена | «Тема не задана», красная точка |
| `planned` | тема есть, генерация не начиналась | «В плане», серая точка |
| `generating` | агент пишет пост | «Генерируется» |
| `needs_review` | пост готов, ждёт человека | «На ревью», жёлтая точка |
| `approved` | одобрен, ждёт времени публикации | «Готов», зелёная точка |
| `published` | опубликован | «Опубликован», серая точка |
| `failed` | генерация или доставка упали | «Ошибка», красная точка |
| `skipped` | слот пропущен вручную | приглушённый |

### Режим публикации проекта

`review` — каждый пост ждёт одобрения. `auto` — пост с полностью зелёными
проверками уходит сам, любое нарушение отправляет на ревью.

### Слои проверок

`format` | `rules` | `grounding` | `image`

### Статус запроса на вход

`pending` — ссылка выдана, бот ещё не получил `/start`; `confirmation` —
получил, ждём нажатия кнопки; `approved` — вход подтверждён; `denied` —
пользователь нажал «Это не я». Истёкший или неизвестный запрос отвечает `404`
с телом `{ "status": "expired" }`.

### Назначение вызова модели

`generate` | `judge` | `claims` | `vision` | `caption` | `embedding` |
`derive_rules`

---

## 3. Аутентификация

Вход через Telegram-бота. Почты, паролей и отдельной регистрации нет:
пользователь заводится при первом подтверждённом входе.

```
POST   /api/auth/login                               → 201 {login_request}
GET    /api/auth/login/status?request={browser_token} → 200 {status} | 404
POST   /api/auth/logout                              → 204
GET    /api/me                                       → 200 {user}
```

`POST /api/auth/login` не требует ни тела, ни сессии, но требует совпадения
Origin. Ответ:

```json
{ "browser_token": "8f3…",
  "telegram_url": "https://t.me/autopost_auth_bot?start=login_8f3…",
  "expires_at": "2026-09-11T18:10:00+03:00" }
```

`browser_token` в API не повторяет `telegram_token` из ссылки — это разные
токены, второй фронтенду не отдаётся.

`GET /api/auth/login/status` фронтенд опрашивает раз в полторы секунды:

```json
{ "status": "pending" }
```

`status`: `pending` — ссылка выдана, подтверждения ещё нет; `confirmation` —
пользователь открыл бота, ждём нажатия кнопки; `approved` — вход выполнен,
сессионная cookie поставлена этим же ответом, в теле дополнительно
`{ "user": …, "csrf": "…" }`; `denied` — пользователь нажал «Это не я».
Неизвестный или истёкший `browser_token` — `404` с телом
`{ "status": "expired" }`, фронтенд предлагает начать вход заново.

Запрос на вход живёт 10 минут, сессия — 365 дней. Лимит: 10 попыток входа с
одного IP за 5 минут, дальше `429` с `Retry-After: 300`.

`user`:

```json
{ "id": 1, "telegram_user_id": "101", "telegram_username": "user_101",
  "display_name": "Иван Петров", "created_at": "...", "common_prompt": "..." }
```

Коды ошибок: `login_request_expired`, `login_denied`, `telegram_unavailable`
(`503`, бот недоступен — вход временно невозможен), `login_not_allowed`
(`403`, вход по списку разрешённых включён, этого пользователя в нём нет).

### Общий промпт пользователя

```
PUT    /api/me/prompt       {prompt}                 → 200 {common_prompt}
```

Один на все проекты пользователя. Системный промпт сервера через API
**не отдаётся и не редактируется**.

---

## 4. Проекты

```
GET    /api/projects                                 → 200 [project_summary]
POST   /api/projects        {name, timezone}         → 201 {project}
GET    /api/projects/{id}                            → 200 {project}
PUT    /api/projects/{id}   {...}                    → 200 {project}
DELETE /api/projects/{id}                            → 204
```

`project_summary` — для переключателя проектов в боковой панели:

```json
{ "id": 3, "name": "Агротех", "channel_title": "@agrotech",
  "publication_mode": "review",
  "counts": { "needs_review": 1, "no_topic": 3, "planned": 9 } }
```

`project` — полный:

```json
{ "id": 3, "name": "Агротех", "timezone": "Europe/Moscow",
  "language": "ru", "audience": "...", "tone": "...",
  "project_prompt": "...",
  "publication_mode": "review",
  "generation_lead_minutes": 1440,
  "media_reuse_days": 30,
  "channel": { "configured": true, "chat_id": "@agrotech",
               "status": "ok", "checked_at": "..." },
  "media": { "total": 128, "available": 82 } }
```

Редактируемые через `PUT`: `name`, `timezone`, `language`, `audience`, `tone`,
`project_prompt`, `publication_mode`, `generation_lead_minutes`,
`media_reuse_days`.

### Канал проекта

```
PUT    /api/projects/{id}/channel  {bot_token, chat_id}  → 200 {channel}
POST   /api/projects/{id}/channel/check                  → 200 {channel}
DELETE /api/projects/{id}/channel                        → 204
```

`bot_token` принимается, но никогда не возвращается. В ответе только
`configured: true`.

---

## 5. Рубрики

```
GET    /api/projects/{id}/rubrics                    → 200 [rubric]
POST   /api/projects/{id}/rubrics  {name, instructions} → 201 {rubric}
PUT    /api/projects/{id}/rubrics/{rubric_id}        → 200 {rubric}
DELETE /api/projects/{id}/rubrics/{rubric_id}        → 204
```

```json
{ "id": 5, "name": "Кейс", "instructions": "...", "enabled": true }
```

Удаление рубрики, на которую ссылаются слоты, отвечает `409`
`rubric_in_use`.

---

## 6. Правила проверки

```
GET    /api/projects/{id}/rules                      → 200 [rule]
PUT    /api/projects/{id}/rules  {rules: [rule]}     → 200 [rule]
POST   /api/projects/{id}/rules/derive               → 202 {operation_id}
```

```json
{ "id": 12, "text": "Каждый пост заканчивается вопросом",
  "severity": "block", "enabled": true, "origin": "derived", "position": 3 }
```

`derive` просит агента разобрать промпт проекта на пункты. Результат операции —
**предложение**, которое человек правит и сохраняет через `PUT`. Сам по себе
`derive` ничего не записывает.

`severity`: `block` — нарушение отправляет пост на доработку, `warn` —
только помечается для редактора.

---

## 7. Контент-план

```
GET    /api/projects/{id}/plan?from=2026-10-01&to=2026-10-31  → 200 [slot]
POST   /api/projects/{id}/plan  {publish_at, rubric_id, topic} → 201 {slot}
PATCH  /api/projects/{id}/plan/{slot_id}                       → 200 {slot}
DELETE /api/projects/{id}/plan/{slot_id}                       → 204
POST   /api/projects/{id}/plan/{slot_id}/generate              → 202 {operation_id}
POST   /api/projects/{id}/plan/{slot_id}/skip                  → 200 {slot}
```

`from` и `to` — даты включительно в таймзоне проекта. Диапазон не больше
92 дней.

`slot`:

```json
{ "id": 41,
  "publish_at": "2026-10-09T18:00:00+03:00",
  "generate_at": "2026-10-08T18:00:00+03:00",
  "rubric": { "id": 7, "name": "Подборка" },
  "topic": "Разобрать 5 ошибок при хранении зерна. Упомянуть влажность 14% и температуру не выше +10 °C.",
  "status": "needs_review",
  "post": { "id": 77, "title": "5 ошибок при хранении зерна",
            "excerpt": "Влажность выше 14% — главная причина…",
            "media_thumb_url": "/api/projects/3/media/42/file?size=thumb",
            "checks_summary": { "passed": false, "blocking": 0, "warnings": 1 } } }
```

`post` равен `null`, пока пост не сгенерирован. Этого набора полей достаточно
для карточки предпросмотра по наведению из мокапа — дополнительный запрос за
полным постом не нужен.

`PATCH` принимает `publish_at`, `rubric_id`, `topic`. Правка `topic` у слота,
пост которого уже сгенерирован, отвечает `409` `post_already_generated` —
сначала нужно `regenerate` или удаление поста.

`generate` на слоте без темы отвечает `400` `slot_topic_required`.

---

## 8. Посты

```
GET    /api/projects/{id}/posts?status=needs_review         → 200 [post_summary]
GET    /api/projects/{id}/posts/{post_id}                   → 200 {post}
PATCH  /api/projects/{id}/posts/{post_id}  {post_text?, media_asset_id?} → 200 {post}
POST   /api/projects/{id}/posts/{post_id}/approve           → 200 {post}
POST   /api/projects/{id}/posts/{post_id}/reject            → 200 {post}
POST   /api/projects/{id}/posts/{post_id}/regenerate        → 202 {operation_id}
```

`post`:

```json
{ "id": 77, "slot_id": 41, "status": "needs_review",
  "post_text": "…", "char_count": 412,
  "media": { "asset_id": 42, "caption": "Зернохранилище, металлические силосы, закат",
             "url": "/api/projects/3/media/42/file",
             "rationale": "Тема о хранении зерна, на снимке силосы",
             "last_used_at": null },
  "generation": { "provider": "codex", "model": "gpt-5.6-terra",
                  "reasoning_effort": "medium", "iterations": 2,
                  "generated_at": "..." },
  "validation": { … см. раздел 9 … },
  "published": null }
```

`PATCH` с ручной правкой текста запускает перепроверку слоями 1 и 3
синхронно — они не требуют обращения к модели для формальной части — и
возвращает обновлённый `validation`. Правка одобренного поста сбрасывает
статус в `needs_review`: изменённый пост требует повторного одобрения.

---

## 9. Отчёт проверок

Одна структура для правой панели и для карточки предпросмотра.

```json
{ "passed": false, "iterations": 2,
  "layers": [
    { "layer": "format", "passed": true, "score": "6/6",
      "items": [ { "key": "length", "passed": true, "detail": "412 из 4096" } ] },

    { "layer": "rules", "passed": true, "score": "4/4",
      "items": [ { "rule_id": 12, "text": "Вопрос в конце", "passed": true,
                   "evidence": "Какую ошибку вы встречали чаще всего?" } ] },

    { "layer": "grounding", "passed": false,
      "items": [ { "claim": "−30% потерь", "verdict": "unsupported",
                   "span": [120, 131],
                   "detail": "Отсутствует в теме слота" } ] },

    { "layer": "image", "passed": true,
      "items": [ { "asset_id": 42, "verdict": "match",
                   "detail": "Зернохранилище, силосы" } ] }
  ] }
```

`verdict` слоя `grounding`: `supported` | `unsupported` | `contradicted`.
`verdict` слоя `image`: `match` | `weak` | `mismatch`.
`span` — смещения в символах в `post_text`, для подсветки фрагмента.

---

## 10. Пул изображений

```
GET    /api/projects/{id}/media?available=true&q=силос&limit=60&cursor=…
                                                     → 200 {items, next_cursor}
POST   /api/projects/{id}/media                      → 202 {operation_id}
GET    /api/projects/{id}/media/{asset_id}/file?size=thumb|full
PATCH  /api/projects/{id}/media/{asset_id}  {caption?, enabled?} → 200 {asset}
DELETE /api/projects/{id}/media/{asset_id}           → 204
POST   /api/projects/{id}/media/{asset_id}/recaption → 202 {operation_id}
```

Загрузка — `multipart/form-data`, поле `files`, до 20 файлов за запрос.
Принимаются `image/jpeg`, `image/png`, `image/webp`. Предельный размер файла
берётся из настроек проекта, по умолчанию 10 МБ; превышение — `413`
`media_too_large`.

Подпись и эмбеддинг считаются асинхронно, поэтому ответ `202`. До их появления
изображение отдаётся со статусом `pending` и в подборе не участвует.

`asset`:

```json
{ "id": 42, "url": "/api/projects/3/media/42/file",
  "caption": "Зернохранилище, металлические силосы, закат",
  "caption_status": "ready",
  "width": 1600, "height": 900, "bytes": 482113,
  "enabled": true, "use_count": 0, "last_used_at": null,
  "available": true }
```

`caption_status`: `pending` | `ready` | `failed`.
`available` — прошёл ли актив политику повторов `media_reuse_days` и включён ли.

`q` — поиск по подписи. При заданном `q` бэкенд использует векторный поиск,
при пустом — сортировку по дате загрузки.

---

## 11. История и операции

```
GET    /api/projects/{id}/operations?limit=50        → 200 [operation]
GET    /api/projects/{id}/operations/{operation_id}  → 200 {operation}
GET    /api/projects/{id}/publications?limit=50      → 200 [publication]
```

`operation` содержит `purpose`, `status`, время начала и конца, `error`.
Автором действия может быть только владелец проекта либо планировщик, поле
`actor`: `user` | `scheduler`.

---

## 12. Что фронтенд может разрабатывать на заглушках

Все перечисленные ответы детерминированы и не зависят от модели, поэтому
фронтенд может идти на моках, не дожидаясь бэкенда:

- список проектов и переключатель;
- контент-план за месяц со всеми восемью статусами слотов;
- карточка предпросмотра — данных из `slot.post` достаточно;
- правая панель поста вместе с отчётом проверок;
- пул изображений, включая `caption_status: pending`;
- формы настроек проекта, рубрик и правил;
- общий промпт пользователя.

Асинхронные сценарии (`202` плюс поллинг) моков требуют отдельных: генерация
поста, перегенерация, загрузка изображений, `derive` правил.

Экран входа тоже мокается отдельно: у него собственный поллинг статуса с
четырьмя исходами (`pending`, `confirmation`, `approved`, `denied`) плюс
истёкший запрос. Вид и текст берутся из страницы входа FakeTG
(`~/Desktop/FakeTG/mockups/telegram-web/storychat-telegram-auth.mjs`, функция
`loginPage`): кнопка «Войти через Telegram», затем ссылка «Открыть Telegram»,
спиннер с подписью «Ожидаем подтверждение», на отказ и истечение — красный
текст и кнопка «Попробовать снова».

---

## 13. Чего в API нет намеренно

- Системного промпта сервера — он не отдаётся и не редактируется через API.
- Ролей, участников, приглашений, администратора.
- Регистрации, смены пароля, восстановления доступа — паролей нет.
- `telegram_token` из диплинка: он существует только между сервером и ботом.
- Импорта материалов, источников, маршрутов публикации и форматов старого
  контура.
- Учёта расхода модели — появится вместе с биллингом.
