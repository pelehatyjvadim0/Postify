from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

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


def test_installed_wheel_serves_workspace_module_imported_by_application(tmp_path) -> None:
    project_root = Path(__file__).parents[3]
    wheelhouse = tmp_path / "wheelhouse"
    installed = tmp_path / "installed"
    subprocess.run(
        ["uv", "build", "--offline", "--wheel", "--out-dir", str(wheelhouse)],
        cwd=project_root,
        check=True,
        capture_output=True,
        text=True,
    )
    wheel = next(wheelhouse.glob("postify-*.whl"))
    subprocess.run(
        ["uv", "pip", "install", "--offline", "--no-deps", "--target", str(installed), str(wheel)],
        check=True,
        capture_output=True,
        text=True,
    )
    script = """
import asyncio
import json
import httpx
from postify.web.app import create_app
from postify.web.dependencies import WebContainer

class Api:
    def bootstrap(self):
        return {"activeProject": {"id": 1}}

async def request(path):
    transport = httpx.ASGITransport(app=create_app(WebContainer(api=Api())))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get(path)
        return {"status": response.status_code, "body": response.text}

root = asyncio.run(request("/"))
app = asyncio.run(request("/app.js"))
workspace = asyncio.run(request("/workspace.js"))
print(json.dumps({"root": root, "app": app, "workspace": workspace}))
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(installed)},
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    served = json.loads(result.stdout)

    assert served["root"]["status"] == 200
    assert 'src="app.js"' in served["root"]["body"]
    assert served["app"]["status"] == 200
    assert 'from "./workspace.js"' in served["app"]["body"]
    assert served["workspace"]["status"] == 200
    assert "export async function loadWorkspace" in served["workspace"]["body"]
