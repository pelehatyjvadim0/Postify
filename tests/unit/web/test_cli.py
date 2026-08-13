from typer.testing import CliRunner


def test_ui_command_runs_app_factory_on_explicit_loopback_host(monkeypatch) -> None:
    # Break caught: UI command binds publicly or bypasses the application's composition root.
    from postify import cli

    captured: dict[str, object] = {}
    app = object()
    monkeypatch.setattr("postify.web.app.create_app", lambda: app)
    monkeypatch.setattr(
        "uvicorn.run", lambda target, **kwargs: captured.update(target=target, **kwargs)
    )

    result = CliRunner().invoke(cli.app, ["ui", "--host", "127.0.0.1", "--port", "8000"])

    assert result.exit_code == 0
    assert captured == {"target": app, "host": "127.0.0.1", "port": 8000}


def test_ui_refuses_non_loopback_bind_without_explicit_unsafe_mode(monkeypatch) -> None:
    # Поломка review: `--host 0.0.0.0` незаметно открывает unauthenticated mutations.
    from postify import cli

    calls = []
    monkeypatch.setattr(
        "postify.web.app.create_app", lambda **kwargs: ("app", kwargs)
    )
    monkeypatch.setattr("uvicorn.run", lambda *args, **kwargs: calls.append((args, kwargs)))

    refused = CliRunner().invoke(cli.app, ["ui", "--host", "0.0.0.0"])
    allowed = CliRunner().invoke(
        cli.app,
        ["ui", "--host", "0.0.0.0", "--unsafe-external-bind"],
    )

    assert refused.exit_code != 0
    assert "unsafe-external-bind" in refused.output
    assert allowed.exit_code == 0
    assert len(calls) == 1
