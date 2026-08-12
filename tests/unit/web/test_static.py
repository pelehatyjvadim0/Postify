from __future__ import annotations

from tests.unit.web.test_api import ApiClient


class Api:
    def bootstrap(self):
        return {"activeProject": {"id": 1}}


def test_packaged_static_mount_serves_root_and_assets(monkeypatch, tmp_path) -> None:
    # Break caught: Task 8 assets are packaged but only index.html is reachable from the web app.
    from postify.web.app import create_app
    from postify.web.dependencies import WebContainer

    (tmp_path / "index.html").write_text("<main>Postify</main>")
    (tmp_path / "app.js").write_text("export const app = true")
    monkeypatch.setattr("postify.web.app._static_directory", lambda: tmp_path)
    client = ApiClient(create_app(WebContainer(api=Api())))

    root = client.get("/")
    asset = client.get("/app.js")

    assert root.status_code == 200
    assert root.text == "<main>Postify</main>"
    assert asset.status_code == 200
    assert asset.text == "export const app = true"
