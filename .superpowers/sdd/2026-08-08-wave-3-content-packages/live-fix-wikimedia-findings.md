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

## Round 2: RED фильтра MIME

Свежий scoped review выявил Important: namespace `6` возвращает
не только raster images, но и PDF/SVG. Wikimedia adapter брал
первый URL, хотя `LocalMediaProvider` принимает только
`image/jpeg`, `image/png` и `image/webp`.

На базе `22ca149` добавлены два MockTransport node:

- `test_wikimedia_search_skips_unsupported_files_and_requests_mime` — в одном
  response PDF/SVG предшествуют PNG/JPEG/WebP; ожидается первый
  поддерживаемый PNG, один request и `iiprop` с `url` и `mime`;
- `test_wikimedia_search_returns_none_when_no_valid_supported_file_exists` —
  unsupported, missing и malformed entries вместе дают safe `None`.

Baseline non-integration: `325 passed, 42 deselected`. Focused Wikimedia:
`2 failed, 2 passed`; retained: `325 passed, 44 deselected`; полный
non-integration: `2 failed, 325 passed, 42 deselected`.

Оба RED воспроизведены по ожидаемой причине: adapter возвращает
PDF как в mixed, так и в all-invalid fixture, а request просит
только `iiprop=url`. Production не изменялся; сеть не вызывалась.

## Round 2: GREEN report

Единственный API request теперь просит `iiprop=url|mime`. Adapter обходит все
pages и их `imageinfo`, возвращая первый непустой URL только при точном MIME
`image/jpeg`, `image/png` или `image/webp`; missing, malformed и unsupported
entries пропускаются. HTTP/JSON safe-`None` handling и число requests сохранены.

- Focused Wikimedia: `4 passed`.
- Retained media adapters: `24 passed`.
- Full non-integration: `327 passed, 42 deselected`.
- `compileall`, `ruff check src`, `uv lock --check`, `git diff --check`: GREEN.
- Live query `PostgreSQL database` через `PublicHttpTransport`: returned URL
  прошёл strict MIME whitelist; URL не выводился.
- Integration с заданным `TEST_DATABASE_URL`: `7 passed, 327 deselected,
  35 errors`; внешний PostgreSQL отклонил соединение, поскольку роль `postify`
  отсутствует.
