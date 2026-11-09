"""Check a local build or deployed GitHub Pages replay in Chromium."""
import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

from playwright.sync_api import expect, sync_playwright


def verify(url: str, channel: str | None, screenshot: Path | None) -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel=channel)
        page = browser.new_page(viewport={"width": 1440, "height": 900}, reduced_motion="reduce")
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        response = page.goto(url, wait_until="domcontentloaded")
        assert response and response.ok
        expect(page.locator("#cars tr")).to_have_count(24)
        expect(page.locator("#markers circle")).to_have_count(24)
        expect(page.get_by_role("heading", name="ピットウォール", exact=True)).to_be_visible()
        expect(page.get_by_role("link", name="PIT WALL")).to_have_attribute("aria-current", "page")
        page.get_by_role("button", name="GAP", exact=True).click()
        expect(page.get_by_role("columnheader", name="GAP", exact=True)).to_be_visible()
        expect(page.locator("#replay-controls")).to_be_hidden()
        assert " L" not in page.locator("#current-trace").get_attribute("d")
        assert page.locator("#previous-trace").get_attribute("d") == ""
        page.get_by_role("button", name="DEMO DRIVER 08").click()
        expect(page.get_by_role("button", name="DEMO DRIVER 08")).to_have_attribute("aria-pressed", "true")
        page.get_by_role("button", name="再生", exact=True).click()
        expect(page.get_by_role("button", name="一時停止")).to_be_visible()
        page.get_by_role("link", name="REPLAY", exact=True).click()
        expect(page.locator("#seek")).not_to_have_value("0")
        page.get_by_role("button", name="SC導入へ").click()
        expect(page.locator("#flag")).to_have_text("SAFETY CAR")
        expect(page.locator("#recommend")).not_to_have_text("推奨 N/A")
        expect(page.locator("#plans tr")).to_have_count(3)
        assert " L" in page.locator("#previous-trace").get_attribute("d")

        def seek(i: int) -> None:
            page.locator("#seek").evaluate("(slider, i) => { slider.value = i; slider.dispatchEvent(new Event('input')); }", i)

        seek(26)
        trace = page.locator("#current-trace").get_attribute("d")
        assert " L" in trace and page.locator("#previous-trace").get_attribute("d") == ""
        marker = page.locator('#markers [data-selected="true"]')
        assert trace.endswith(marker.get_attribute("cx") + " " + marker.get_attribute("cy"))
        page.get_by_label("ドライバー", exact=True).select_option("1")
        assert page.locator("#current-trace").get_attribute("d") != trace
        page.get_by_role("link", name="CIRCUIT").click()
        expect(page.locator("#focus-panel #circuit-panel")).to_be_visible()
        page.get_by_role("link", name="REPLAY", exact=True).click()
        seek(0)
        assert " L" not in page.locator("#current-trace").get_attribute("d")
        assert page.locator("#previous-trace").get_attribute("d") == ""
        page.get_by_role("link", name="PS5 LIVE", exact=True).click()
        expect(page.get_by_role("link", name="このPCのライブ画面を開く")).to_have_attribute("href", "http://127.0.0.1:8000/")
        expect(page.locator("#pit-wall-grid")).to_be_hidden()
        page.get_by_role("link", name="REPLAY", exact=True).click()
        seek(72)
        page.get_by_role("link", name="LAP RECORDS", exact=True).click()
        expect(page.locator("#timing-laps tr")).to_have_count(2)
        page.get_by_label("周回", exact=True).select_option("1")
        expect(page.locator("#timing-minis .mini-record-row")).to_have_count(30)
        expect(page.locator("#timing-laps tr.selected")).to_contain_text("30/30")
        page.get_by_role("link", name="REPLAY", exact=True).click()
        if screenshot:
            seek(72)
            page.get_by_role("link", name="PIT WALL").click()
            expect(page.get_by_role("heading", name="ピットウォール", exact=True)).to_be_visible()
            page.screenshot(path=screenshot)

        phone = browser.new_page(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
        phone.goto(url)
        expect(phone.locator("#cars tr")).to_have_count(24)
        expect(phone.get_by_role("button", name="一時停止")).to_be_visible()
        assert phone.evaluate("document.documentElement.scrollWidth === innerWidth")
        assert not errors, errors
        browser.close()
    print("Pages smoke passed: default pit wall, 24 cars, selected-car traces, rewind, safety car, strategy, and mobile layout.")


def main():
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
