"""Check the local build or published PS5 live connection page in Chromium."""

import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

from playwright.sync_api import expect, sync_playwright


def verify(url: str, channel: str | None, screenshot: Path | None) -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel=channel)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        response = page.goto(url)
        assert response and response.ok
        expect(page.get_by_role("heading", name="PS5 ライブ接続", exact=True)).to_be_visible()
        expect(page.get_by_role("link", name="このPCのライブ画面を開く")).to_have_attribute(
            "href", "http://127.0.0.1:8000/"
        )
        expect(page.get_by_role("combobox", name="画面", exact=True)).to_have_count(0)
        expect(page.get_by_text("DEMO / 合成データ", exact=True)).to_have_count(0)
        if screenshot:
            page.screenshot(path=screenshot)

        phone = browser.new_page(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
        phone.goto(url)
        expect(phone.get_by_role("link", name="このPCのライブ画面を開く")).to_be_visible()
        assert phone.evaluate("document.documentElement.scrollWidth === innerWidth")
        browser.close()
    print("Pages smoke passed: PS5 connection page, live dashboard link, and mobile layout.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--url")
    group.add_argument("--directory", type=Path)
    parser.add_argument("--channel")
    parser.add_argument("--screenshot", type=Path)
    args = parser.parse_args()
    if args.url:
        verify(args.url, args.channel, args.screenshot)
        return
    with ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=args.directory)) as http:
        thread = Thread(target=http.serve_forever, daemon=True)
        thread.start()
        try:
            verify(f"http://127.0.0.1:{http.server_port}/", args.channel, args.screenshot)
        finally:
            http.shutdown()
            thread.join()


if __name__ == "__main__":
    main()
