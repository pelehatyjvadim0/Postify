from types import SimpleNamespace


def test_database_engine_bounds_connect_and_pool_waits(monkeypatch) -> None:
    # Поломка: scheduler worker может бесконечно ждать TCP connect или pool slot.
    from postify.infrastructure.database import engine as engine_module

    captured = {}
    expected = object()

    def build(url: str, **kwargs):
        captured.update(url=url, **kwargs)
        return expected

    monkeypatch.setattr(engine_module, "create_engine", build)

    result = engine_module.create_engine_from_settings(
        SimpleNamespace(database_url="postgresql+psycopg://db/postify")
    )

    assert result is expected
    assert captured == {
        "url": "postgresql+psycopg://db/postify",
        "connect_args": {"connect_timeout": 5},
        "pool_timeout": 5,
    }
