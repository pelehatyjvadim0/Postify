# Live fix: Wikimedia Commons search

Read-only live proof через production `PublicHttpTransport` выявил два
последовательных root cause:

1. текущий request без `User-Agent` получает Wikimedia HTTP 403 с требованием
   задать идентификатор клиента;
2. после User-Agent текущий generic search возвращает 0 usable pages;
   с `gsrnamespace=6` тот же query возвращает file pages с `imageinfo`.

Adapter обязан отправлять стабильный не-секретный Postify User-Agent и ограничивать
generator search namespace файлов (`6`). HTTP status/JSON ошибки остаются
безопасным `None`. Tests используют MockTransport и не вызывают сеть.

Production scope: только `src/postify/adapters/media/wikimedia.py`. После fix —
scoped review и повтор live query; затем заново полный branch gate.

## RED evidence

База: `63abe0b`. Production не изменялся. Existing positive MockTransport
node сохранил прежний intent одного request и original `imageinfo` URL,
но дополнительно требует точные `User-Agent: Postify/0.1` и
`gsrnamespace=6`. Текущий request даёт `("python-httpx/0.28.1", None)`,
поэтом node падает ровно по обоим live root cause.

Отдельный node подтвердил safe `None` для transport и JSON errors.
Baseline: `324 passed, 42 deselected`; RED: `1 failed`; retained:
`324 passed, 43 deselected`; full non-integration:
`1 failed, 324 passed, 42 deselected`. Сеть не вызывалась.

## GREEN report

Реализация добавляет ровно два поля к единственному Commons request:
`headers={"User-Agent": "Postify/0.1"}` и `gsrnamespace="6"`.
Обработка HTTP/JSON ошибок, число запросов и return contract не менялись.

- Focused: `2 passed`.
- Media adapters: `22 passed`.
- Live query через `PublicHttpTransport`: вернул `("wikimedia", imageinfo_url)`.
- Full non-integration: `325 passed, 42 deselected`.
- Integration: `42 passed, 325 deselected`.
- `compileall`, `ruff check src` и `git diff --check`: GREEN.
