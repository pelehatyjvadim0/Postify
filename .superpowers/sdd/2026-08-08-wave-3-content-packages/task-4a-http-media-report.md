# Отчёт Task 4A

## Статус

Реализация завершена в границах задачи. Focused GREEN пройден.

## Коммит

`Защитил HTTP загрузку статей и медиа`

## Файлы

- `src/postify/adapters/http/__init__.py`
- `src/postify/adapters/http/public_url_policy.py`
- `src/postify/adapters/articles/http_article_extractor.py`
- `src/postify/adapters/media/local_media_provider.py`

## Проверки

- Focused: `uv run pytest tests/unit/adapters/http/test_public_url_policy.py tests/unit/adapters/articles/test_http_article_extractor.py tests/unit/adapters/media/test_local_media_provider.py -q` — 47 passed.
- Полный: `uv run pytest -m 'not integration' -q` — 275 passed, 16 failed, 41 deselected. Сбои находятся вне границ Task 4A: незавершённые AI, application ports и domain content; один integration-узел ожидает изменение `bootstrap.py`, запрещённое brief.
- `uv run python -m compileall -q src` — успешно.
- `uv run ruff check src` — успешно.
- `git diff --check` — успешно.

## Self-review

- URL policy отвергает небезопасные схемы, userinfo, пустой или некорректный DNS и любой непубличный адрес без раскрытия URL.
- Article и media при внедрённой policy проверяют URL до открытия stream, отключают redirects и читают тело только chunks с ранней проверкой Content-Length.
- Media записывает допустимые файлы через временный файл и atomic replace; delete и cleanup не затрагивают symlink или путь вне root.
- HTML отдаёт один приоритетный источник текста и группирует изображения по `og`, `twitter`, `article` независимо от порядка DOM.

## Concerns

- Внедрение одной policy в bootstrap принадлежит следующему разрешённому срезу: текущий brief прямо запрещает менять `bootstrap.py`. Конструкторы обоих адаптеров уже принимают одинаковую injectable policy.

## Fix round 1 после review `a51e845`

Статус: `RED_READY`. Production не менялся.

- `13` новых node ID и `12` усиленных DNS node ID дают ровно
  `25 failed, 42 deselected` в узком Task 4A запуске.
- Сохранённые article/media/public URL nodes отдельно:
  `35 passed, 24 deselected`.
- Focused Task 4A + bootstrap/ports: `32 failed, 35 passed`; из них
  `7` — уже известные RED public ports/прежнего bootstrap wiring.
- Полный non-integration: `41 failed, 263 passed, 41 deselected`:
  `25` Task 4A RED + `16` известных Task 4B/4C RED.
- PostgreSQL retained gate: `6 failed, 35 passed, 304 deselected`; шесть
  RED без изменений относятся к Task 4C.
- Сеть не вызывалась: HTTP остался на fake resolver,
  `httpx.MockTransport` и fake underlying network backend.

Контракты fix round:

- `url_policy` — обязательная non-`None` dependency обоих адаптеров;
  все позитивные tests теперь передают явный structurally-safe fake.
- Отдельного `UserInputError` в проекте нет. Malformed/zero/overflow
  port нормализуется существующим `UnsafePublicUrlError`
  (`code=unsafe_url`) до resolver/HTTP, без URL/host в тексте.
- DNS решается один раз в `PublicNetworkBackend`; underlying
  `connect_tcp` получает тот же public IP, а hostname остаётся выше
  backend для HTTP Host/TLS SNI. URL rewriting на IP не допускается.
- `PublicHttpTransport` wiring в `_open_import_resources` зафиксирован
  отдельным RED в `test_ports.py`, поскольку изменение
  `bootstrap.py` лежит в Task 4B.
- `delete` отвергает symlink в любом промежуточном компоненте,
  даже если resolved target остаётся в media root.
- Cleanup filesystem failure возвращает recoverable `MediaAcquireError`
  с `code=media_failed` без absolute path; файл остаётся для retry.
- `LocalMediaProvider` сам сортирует недоверенный вход
  `og → twitter → article`; порядок parser не является его предусловием.
