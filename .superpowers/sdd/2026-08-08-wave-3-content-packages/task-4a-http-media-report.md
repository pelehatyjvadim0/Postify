# Отчёт Task 4A

## Статус

Fix round 1 реализован в разрешённой production-границе. Scoped GREEN пройден.

## Коммиты

- `a51e845 Защитил HTTP загрузку статей и медиа`
- Текущий fix round: `Устранил повторное DNS-разрешение HTTP и усилил media safety`.

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

## Self-review

- `url_policy` обязательна и отвергает `None` в обоих адаптерах; обход проверки до HTTP исключён.
- `validate()` форсирует `parsed.port` и диапазон до DNS; ошибки имеют только стабильный `unsafe_url` без URL/host и скрытой причины.
- DNS перенесён на фактический `connect_tcp`: один resolver call на соединение, mixed/private/invalid ответы не доходят до socket, underlying backend получает проверенный IP.
- `PublicHttpTransport` действительно устанавливает `PublicNetworkBackend` в httpcore pool. URL и origin hostname не переписываются, поэтому Host и TLS SNI остаются исходными.
- Прямой production import `httpcore` отражён в `pyproject.toml` и `uv.lock`; локальная версия — `1.0.9`, `httpx` — `0.28.1`.
- `delete()` проверяет lexical containment и каждый существующий компонент на symlink до unlink; target не удаляется.
- `cleanup()` нормализует filesystem failures в `media_failed` без path и оставляет неудалённый файл для retry.
- Media candidates стабильно сортируются самим provider по `og → twitter → article`.

## Concerns

- Два bootstrap RED остаются намеренно: обязательную policy и новый transport должен связать Task 4B; `bootstrap.py` запрещён текущим brief.
- Остальные 15 full-gate RED принадлежат Task 4B/4C. В scoped Task 4A открытых замечаний нет.
