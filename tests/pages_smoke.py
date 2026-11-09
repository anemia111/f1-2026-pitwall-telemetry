"""Check a local build or deployed GitHub Pages replay in Chromium."""
import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

from playwright.sync_api import expect, sync_playwright


def verify(url: str, channel: str | None) -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel=channel)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        response = page.goto(url, wait_until="domcontentloaded")
        assert response and response.ok
        expect(page.locator("#cars tr")).to_have_count(24)
        expect(page.locator("#markers circle")).to_have_count(24)
        expect(page.get_by_role("heading", name="2026 ピットウォール")).to_be_visible()
        page.get_by_role("button", name="DEMO DRIVER 08").click()
        expect(page.get_by_role("button", name="DEMO DRIVER 08")).to_have_attribute("aria-pressed", "true")
        page.get_by_role("button", name="再生", exact=True).click()
        expect(page.get_by_role("button", name="一時停止")).to_be_visible()
        expect(page.locator("#seek")).not_to_have_value("0")
        page.get_by_role("button", name="SC導入へ").click()
        expect(page.locator("#flag")).to_have_text("SAFETY CAR")
        expect(page.locator("#recommend")).not_to_have_text("推奨 N/A")
        expect(page.locator("#plans tr")).to_have_count(3)
        phone = browser.new_page(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
        phone.goto(url)
        expect(phone.locator("#cars tr")).to_have_count(24)
        assert phone.evaluate("document.documentElement.scrollWidth === innerWidth")
        assert not errors, errors
        browser.close()
    print("Pages smoke passed: 24 cars, map, replay, driver selection, safety car, strategy, and mobile layout.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--url")
    group.add_argument("--directory", type=Path)
    parser.add_argument("--channel")
    args = parser.parse_args()
    if args.url:
        verify(args.url, args.channel)
        return
    with ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=args.directory)) as http:
        thread = Thread(target=http.serve_forever, daemon=True)
        thread.start()
        try:
            verify(f"http://127.0.0.1:{http.server_port}/", args.channel)
        finally:
            http.shutdown()
            thread.join()


if __name__ == "__main__":
    main()
