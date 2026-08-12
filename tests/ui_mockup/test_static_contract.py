from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).parents[2]


class ShellCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: set[str] = set()
        self.assets: list[str] = []
        self.language: str | None = None
        self.has_polite_region = False

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


def test_mockup_exposes_the_application_shell_offline() -> None:
    html = (ROOT / "ui-mockup/index.html").read_text()
    parser = ShellCollector()
    parser.feed(html)

    assert parser.language == "ru"
    assert {
        "app-nav",
        "farm-switcher",
        "screen-root",
        "demo-reset",
        "detail-layer",
        "toast-region",
    } <= parser.ids
    assert parser.has_polite_region
    assert parser.assets == ["styles.css", "app.js"]


def test_styles_cover_the_visual_and_accessibility_boundaries() -> None:
    css = (ROOT / "ui-mockup/styles.css").read_text()

    for token in (
        "--canvas",
        "--surface",
        "--ink",
        "--forest",
        "--olive",
        "--amber",
    ):
        assert token in css
    assert ":focus-visible" in css
    assert "prefers-reduced-motion" in css
    assert "@media (max-width: 767px)" in css
