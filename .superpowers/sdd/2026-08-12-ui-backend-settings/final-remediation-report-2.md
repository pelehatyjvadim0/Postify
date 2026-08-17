# Final remediation evidence report 2 — 2026-08-17

Tested boundary: product behavior `497746a`; current committed evidence tree
`e6af284`. Commits `143ce0a` and `e6af284` only record/fix durable evidence
after the product boundary. The prior `final-remediation-report.md` remains an
historical report for its earlier commands and counts.

## PostgreSQL 16 boundary

The trace records these actual no-secret provisioning and successful start
commands for the dedicated user-owned loopback test cluster:

```sh
/usr/lib/postgresql/16/bin/initdb -D /dev/shm/postify-sssf-pg16 --username=postify_gate --auth=trust --encoding=UTF8 --no-locale
mkdir -p /dev/shm/postify-sssf-pg16-socket
/usr/lib/postgresql/16/bin/pg_ctl -D /dev/shm/postify-sssf-pg16 -l /dev/shm/postify-sssf-pg16.log -o "-h 127.0.0.1 -p 55434 -k /dev/shm/postify-sssf-pg16-socket" start
```

The initial start without `-k` failed; it is not represented as a successful
gate. The command above started the server. `pg_isready` accepted the loopback
connection and the server reported PostgreSQL `16.14`, UTF-8. No password or
production DSN is stored here.

## Deterministic quality/07 results

The factory injected its isolated test DSN and temporary directories without
printing credentials. Every referenced log reports exit `0`:

| Artifact | Exact logged command | Result |
| --- | --- | --- |
| `07_postgresql16_full_suite/command.log` | `uv run pytest -q` | `741 passed in 51.10s` |
| `07_focused_backend/command.log` | `uv run pytest -p no:cacheprovider -q tests/integration/test_project_runtime_configuration.py tests/integration/test_web_component.py tests/integration/test_web_operation_ownership.py` | `12 passed in 2.03s` |
| `07_browser_ui/command.log` | `uv run pytest -p no:cacheprovider -q tests/ui_mockup/test_browser_flows.py` | `77 passed in 28.51s` |
| `07_installed_wheel/command.log` | `uv run pytest -p no:cacheprovider -q tests/e2e/test_cli_ui.py` | `1 passed in 3.08s` |
| `07_ruff/command.log` | `uv run ruff check .` | `All checks passed!` |
| `07_compileall/command.log` | `uv run python -m compileall -q src` | exit `0`, no output |
| `07_lock/command.log` | `uv lock --check` | `Resolved 43 packages in 0.87ms` |
| `07_node_api/command.log` | `node --check src/postify/web/static/api.js` | exit `0` |
| `07_node_screens/command.log` | `node --check src/postify/web/static/screens.js` | exit `0` |
| `07_node_settings/command.log` | `node --check src/postify/web/static/settings.js` | exit `0` |
| `07_node_app/command.log` | `node --check src/postify/web/static/app.js` | exit `0` |
| `07_diff_worktree/command.log` | `git diff --check` | exit `0` |
| `07_diff_wave/command.log` | `git diff --check 9ce37da..HEAD` | exit `0` |
| `07_visual_evidence/command.log` | `uv run python adws/adw_modules/visual_evidence.py docs/development-loop/evidence/artifacts/2026-08-12-wave-6/manifest.json` | 16 PNG captures valid |

These logs are under
`adws/adw_data/sessions/0b38d798/context_handoff/quality/`.

## Durable visual evidence

`docs/development-loop/evidence/artifacts/2026-08-12-wave-6/manifest.json`
records product commit `497746a`, capture command
`uv run python docs/development-loop/evidence/artifacts/2026-08-12-wave-6/capture.py`,
SHA-256, byte size, dimensions and overflow measurements. Its 16 existing PNG
records are the seven desktop and seven mobile ready screens plus desktop
loading and mobile error. Every record has `horizontal_overflow=false`.

## Status

The three historical blockers remain closed: route/channel-safe schedule and
retry, atomic queued/leased restart recovery with exactly-once regression, and
complete empty/populated Journal plus attempt code/reason. Safe `.env` loading
and the SQLAlchemy-to-libpq `pg_dump` target remain covered. Independent review
approved `e6af284` with no blocker. No merge, push, main-branch validation,
worktree deletion or cache cleanup is claimed.
