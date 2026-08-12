from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).parents[2]
STATIC = ROOT / "src/postify/web/static"


class ShellCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: set[str] = set()
        self.assets: list[str] = []
        self.language: str | None = None
        self.has_polite_region = False
        self.brand_mark_tag: str | None = None
        self.brand_leaf_count = 0
        self.settings_href: str | None = None

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        values = dict(attrs)
        if tag == "html":
            self.language = values.get("lang")
        if element_id := values.get("id"):
            self.ids.add(element_id)
        if tag == "script" and values.get("src"):
            self.assets.append(values["src"] or "")
        if tag == "link" and values.get("rel") == "stylesheet":
            self.assets.append(values.get("href") or "")
        if values.get("aria-live") == "polite":
            self.has_polite_region = True
        classes = (values.get("class") or "").split()
        if "brand-mark" in classes:
            self.brand_mark_tag = tag
        if tag == "path" and "brand-leaf" in classes:
            self.brand_leaf_count += 1
        if values.get("data-route") == "settings":
            self.settings_href = values.get("href")


def test_production_frontend_exposes_the_approved_application_shell() -> None:
    # Break caught: packaging falls back to the offline demo or loses the approved shell/logo.
    html = STATIC.joinpath("index.html").read_text()
    parser = ShellCollector()
    parser.feed(html)

    assert parser.language == "ru"
    assert {"app-nav", "farm-switcher", "screen-root", "detail-layer", "toast-region"} <= parser.ids
    assert "demo-reset" not in parser.ids
    assert parser.has_polite_region
    assert parser.assets == ["styles.css", "app.js"]
    assert parser.brand_mark_tag == "svg"
    assert parser.brand_leaf_count == 3
    assert parser.settings_href == "#settings"


def test_frontend_uses_api_without_demo_state() -> None:
    # Break caught: production UI silently restores local demo data instead of showing API state.
    app = STATIC.joinpath("app.js").read_text()
    api = STATIC.joinpath("api.js").read_text()
    screens = STATIC.joinpath("screens.js").read_text()

    assert "INITIAL_STATE" not in app
    assert "Демо-данные" not in app
    assert 'from "./api.js"' in app
    assert 'from "./screens.js"' in app
    assert "AbortController" in app
    assert "fetch(" in api
    assert "fetch(" not in screens
    assert "XMLHttpRequest" not in app + api + screens
    for resource in ("dashboard", "materials", "packages", "queue", "publications", "operations"):
        assert resource in api
    for command in ("approve", "reject", "run-once", "publish-once"):
        assert command in api


def test_styles_retain_visual_accessibility_and_responsive_boundaries() -> None:
    # Break caught: the production move drops the Warm Studio tokens or a control-size breakpoint.
    css = STATIC.joinpath("styles.css").read_text()

    for token in ("--canvas", "--surface", "--ink", "--forest", "--olive", "--amber"):
        assert token in css
    assert ":focus-visible" in css
    assert "prefers-reduced-motion" in css
    assert "@media (max-width: 767px)" in css


def test_wheel_configuration_includes_all_static_assets() -> None:
    # Break caught: the UI works from checkout but disappears from an installed wheel.
    pyproject = ROOT.joinpath("pyproject.toml").read_text()

    for asset in ("web/static/index.html", "web/static/styles.css", "web/static/app.js", "web/static/api.js", "web/static/screens.js"):
        assert asset in pyproject
