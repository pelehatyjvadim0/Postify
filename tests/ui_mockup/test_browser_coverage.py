from playwright.sync_api import expect

from tests.ui_mockup.browser_support import PROJECT, fixture_payloads, install_api


def test_unknown_hash_normalizes_to_workspace_and_detail_escape_restores_opener(page_factory, base_url):
    page = page_factory(); install_api(page)
    page.goto(f"{base_url}/#unknown")
    expect(page.locator('[data-screen="review"]')).to_be_visible()
    assert page.url.endswith('/#review')
    opener = page.locator('[data-action="open-package"]')
    opener.click(); expect(page.locator('#detail-content')).to_be_visible()
    page.keyboard.press('Escape')
