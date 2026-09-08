from pathlib import Path

ROOT = Path(__file__).parents[2]
STATIC = ROOT / "src/postify/web/static"


def test_shell_exposes_only_current_workspace_connections_and_settings_routes():
    html = STATIC.joinpath("index.html").read_text()
    assert all(f'data-route="{route}"' in html for route in ("review", "connections", "settings"))
    assert "data-route=\"overview\"" not in html
    assert 'src="app.js"' in html


def test_static_modules_keep_abortable_api_and_packaged_workspace_module():
    app = STATIC.joinpath("app.js").read_text()
    api = STATIC.joinpath("api.js").read_text()
    pyproject = ROOT.joinpath("pyproject.toml").read_text()
    assert "AbortController" in app and 'from "./workspace.js"' in app
    assert "fetch(" in api and "workspace.js" in pyproject
