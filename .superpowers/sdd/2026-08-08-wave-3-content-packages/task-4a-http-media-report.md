# Отчёт Task 4A

## Статус

Fix round 2 реализован в разрешённой production-границе. Scoped GREEN пройден.

## Коммиты

- `a51e845 Защитил HTTP загрузку статей и медиа`
- Текущий fix round: `Устранил повторное DNS-разрешение HTTP и усилил media safety`.
- Fix round 2 RED: `9b99285 Зафиксировал RED гонки удаления и сетевых маршрутов`.
- Fix round 2 GREEN: `Закрыл сетевые обходы и гонку удаления медиа`.

## Файлы fix round 1

- `src/postify/adapters/http/public_url_policy.py`
- `src/postify/adapters/articles/http_article_extractor.py`
- `src/postify/adapters/media/local_media_provider.py`
- `pyproject.toml`
- `uv.lock`

## TDD и проверки

- Исходный узкий RED: `uv run pytest tests/unit/adapters/http/test_public_url_policy.py tests/unit/adapters/articles/test_http_article_extractor.py tests/unit/adapters/media/test_local_media_provider.py -q -k 'cannot_be_constructed or invalid_port or public_network_backend or intermediate_symlink or cleanup_normalizes or owns_og_twitter'` — 12 failed, 47 deselected.
- Mandatory policy GREEN: `uv run pytest tests/unit/adapters/articles/test_http_article_extractor.py tests/unit/adapters/media/test_local_media_provider.py -q -k cannot_be_constructed` — 4 passed, 30 deselected.
- URL/backend GREEN: `uv run pytest tests/unit/adapters/http/test_public_url_policy.py -q -k 'invalid_port or forbidden_dns_answer or accepts_only or public_network_backend'` — 17 passed, 8 deselected.
- Filesystem/priority GREEN: `uv run pytest tests/unit/adapters/media/test_local_media_provider.py -q -k 'intermediate_symlink or cleanup_normalizes or owns_og_twitter'` — 3 passed, 16 deselected.
- Scoped: `uv run pytest tests/unit/adapters/http/test_public_url_policy.py tests/unit/adapters/articles/test_http_article_extractor.py tests/unit/adapters/media/test_local_media_provider.py -q` — 59 passed.
- Transport binding без сети: локальная проверка подтвердила `PublicHttpTransport._pool._network_backend is transport.network_backend`, общую policy и корректное закрытие transport.
- Полный: `uv run pytest -m 'not integration' -q` — 287 passed, 17 failed, 41 deselected. Все 17 RED относятся к Task 4B/4C: 4 Codex, 8 ports/bootstrap, 1 process content, 4 domain content.
- `uv run python -m compileall -q src` — успешно.
- `uv run ruff check src` — успешно, `All checks passed!`.
- `git diff --check` — успешно.

## RED fix round 2

- База: `14621ce`; production-файлы не изменялись.
- Baseline: scoped-запуск до новых tests — `59 passed`.
- Новые RED: `4 failed` — fallback на второй validated IP, запрет
  `proxy`, запрет `uds`, fd-bound delete при TOCTOU.
- Scoped после tests: `4 failed, 59 passed`.
- Retained отдельно: `59 passed, 4 deselected`.
- DNS/fallback test: fake resolver вызван один раз; fake underlying получает
  два public IP в исходном порядке и ни разу не получает hostname.
- Delete test выполняет реальный `os.unlink`: непосредственно перед
  ним parent переименовывается и заменяется symlink. Тест проверяет
  сохранность одноимённого файла в другом каталоге и удаление файла
  в ранее открытом parent.

## Self-review

- `url_policy` обязательна и отвергает `None` в обоих адаптерах; обход проверки до HTTP исключён.
- `validate()` форсирует `parsed.port` и диапазон до DNS; ошибки имеют только стабильный `unsafe_url` без URL/host и скрытой причины.
- DNS перенесён на фактический `connect_tcp`: один resolver call на соединение, mixed/private/invalid ответы не доходят до socket, underlying backend получает проверенный IP.
- `PublicHttpTransport` действительно устанавливает `PublicNetworkBackend` в httpcore pool. URL и origin hostname не переписываются, поэтому Host и TLS SNI остаются исходными.
- Прямой production import `httpcore` отражён в `pyproject.toml` и `uv.lock`; локальная версия — `1.0.9`, `httpx` — `0.28.1`.
- `delete()` открывает root и intermediate directories через fd с `O_NOFOLLOW`, а удаляет basename относительно открытого parent fd; подмена path не ведёт к другому target.
- `cleanup()` нормализует filesystem failures в `media_failed` без path и оставляет неудалённый файл для retry.
- Media candidates стабильно сортируются самим provider по `og → twitter → article`.

## Concerns

- Два bootstrap RED остаются намеренно: обязательную policy и новый transport должен связать Task 4B; `bootstrap.py` запрещён текущим brief.
- Остальные 15 full-gate RED принадлежат Task 4B/4C.

## Fix round 2 GREEN

- Новый RED: `uv run pytest tests/unit/adapters/http/test_public_url_policy.py tests/unit/adapters/media/test_local_media_provider.py -q -k 'tries_next_validated_ip or rejects_routes_that_bypass or keeps_open_parent_binding'` — 4 failed, 44 deselected.
- HTTP GREEN: `uv run pytest tests/unit/adapters/http/test_public_url_policy.py -q -k 'tries_next_validated_ip or rejects_routes_that_bypass'` — 3 passed, 25 deselected.
- Delete retained GREEN: `uv run pytest tests/unit/adapters/media/test_local_media_provider.py -q -k delete` — 4 passed, 16 deselected.
- Четыре новых GREEN: `uv run pytest tests/unit/adapters/http/test_public_url_policy.py tests/unit/adapters/media/test_local_media_provider.py -q -k 'tries_next_validated_ip or rejects_routes_that_bypass or keeps_open_parent_binding'` — 4 passed, 44 deselected.
- Scoped: `uv run pytest tests/unit/adapters/http/test_public_url_policy.py tests/unit/adapters/articles/test_http_article_extractor.py tests/unit/adapters/media/test_local_media_provider.py -q` — 63 passed.
- Полный: `uv run pytest -m 'not integration' -q` — 291 passed, 17 failed, 41 deselected. Все 17 RED относятся к Task 4B/4C.
- `uv run python -m compileall -q src` — успешно.
- `uv run ruff check src` — `All checks passed!`.
- `uv lock --check` — `Resolved 34 packages`.
- `git diff --check` — успешно.

Self-review round 2: resolver вызывается один раз, весь ответ валидируется до первого socket, `ConnectError` переключает только на следующий уже проверенный IP. Transport отвергает non-`None` proxy/UDS стабильной ошибкой без значения. Delete удерживает fd parent во время `os.unlink`, не следует подменённому symlink и закрывает все открытые descriptors.
