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
