"""Browser end-to-end checks against a running 24-car DEMO instance."""
import argparse
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from time import monotonic, sleep
from urllib.parse import urlparse
from urllib.request import urlopen

from playwright.sync_api import expect, sync_playwright


@contextmanager
def launch(url, key):
    import uvicorn
    from pitwall.server import create_app
    from pitwall.service import Settings

    parsed = urlparse(url)
    host = "0.0.0.0" if key else "127.0.0.1"
    with TemporaryDirectory(prefix="apex-browser-") as directory:
        settings = Settings(mode="DEMO", udp_host="127.0.0.1", udp_port=0, key=key or "")
        app = create_app(settings, Path(directory) / "browser.sqlite3", demo_rate=60)
        server = uvicorn.Server(uvicorn.Config(app, host=host, port=parsed.port or 80,
                                               log_level="warning", access_log=False))
        thread = Thread(target=server.run, daemon=True)
        thread.start()
        try:
            deadline = monotonic() + 12
            while True:
                try:
                    with urlopen(url, timeout=2):
                        break
                except OSError:
                    if monotonic() > deadline or not thread.is_alive():
                        raise
                    sleep(.15)
            yield
        finally:
            server.should_exit = True
            thread.join(timeout=15)
            if thread.is_alive():
                raise RuntimeError("test server did not close")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--channel")
    parser.add_argument("--key")
    parser.add_argument("--screenshot")
    parser.add_argument("--launch", action="store_true", help="Start a temporary test server")
    args = parser.parse_args()
    if args.launch:
        with launch(args.url, args.key):
            verify(args)
    else:
        verify(args)


def verify(args):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel=args.channel)
        page = browser.new_page(viewport={"width": 1440, "height": 900}, accept_downloads=True)
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(args.url)
        if args.key:
            page.get_by_label("アクセスキー").fill(args.key)
            page.get_by_role("button", name="接続", exact=True).click()
        expect(page.locator(".demo-strip")).to_be_visible(timeout=12000)
        expect(page.locator(".timing tbody tr")).to_have_count(24, timeout=12000)
        expect(page.get_by_role("img", name="受信した走行位置と走行軌跡")).to_be_visible()
        expect(page.locator(".mini-rail .rank-overall").first).to_be_visible(timeout=12000)
        expect(page.locator(".mini-rail .rank-personal").first).to_be_visible(timeout=12000)
        expect(page.locator(".leader-sector > .rank-overall").first).to_be_visible(timeout=12000)
        expect(page.locator(".leader-sector > .rank-personal").first).to_be_visible(timeout=12000)
        expect(page.locator(".leader-sector > .rank-other").first).to_be_visible(timeout=20000)
        if args.screenshot:
            page.screenshot(path=args.screenshot)
        with page.expect_response(lambda r: "/api/timing?" in r.url and r.ok):
            page.get_by_role("link", name="LAP RECORDS", exact=True).click()
        expect(page.get_by_text("自動更新中", exact=True)).to_be_visible()
        expect(page.locator(".mini-record-row strong[class^='rank-']").first).to_be_visible()
        with page.expect_response(lambda r: "/api/timing?" in r.url and r.ok, timeout=5000):
            expect(page.get_by_text("· 走行中", exact=False)).to_be_visible()
        page.get_by_role("link", name="DRIVER", exact=True).click()
        expect(page.get_by_role("heading", name="ドライバーテレメトリー")).to_be_visible()
        expect(page.get_by_role("img", name="速度 / km/h")).to_be_visible()
        page.get_by_role("button", name="走行距離", exact=True).click()
        page.get_by_role("button", name="速度 / km/h 拡大").click()
        page.get_by_role("link", name="AI ENGINEER", exact=True).click()
        page.get_by_label("レースエンジニアへの質問").fill("前の車とのギャップは？")
        page.get_by_role("button", name="送信", exact=True).click()
        expect(page.locator(".answer")).to_contain_text("前方")
        page.get_by_role("link", name="LAP COMPARE", exact=True).click()
        expect(page.get_by_label("基準ラップ").locator("option").nth(1)).to_be_attached(timeout=35000)
        expect(page.get_by_text("共通点", exact=False)).to_be_visible(timeout=35000)
        page.get_by_role("link", name="REPLAY", exact=True).click()
        session = page.get_by_role("combobox", name="セッション", exact=True)
        expect(session.locator("option").nth(1)).to_be_attached()
        session.select_option(index=1)
        expect(page.locator(".replay-strip")).to_be_visible()
        with page.expect_download() as export:
            page.get_by_role("link", name="CSV", exact=True).click()
        assert export.value.suggested_filename.endswith(".csv")
        page.get_by_role("button", name="再生", exact=True).click()
        expect(page.get_by_role("button", name="一時停止")).to_be_visible()
        page.get_by_role("button", name="ライブに戻る").click()
        expect(page.locator(".replay-strip")).to_have_count(0)
        phone = browser.new_page(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
        if args.key:
            phone.context.add_cookies(page.context.cookies())
        phone.goto(args.url)
        expect(phone.locator(".timing tbody tr")).to_have_count(24, timeout=12000)
        assert phone.evaluate("document.documentElement.scrollWidth === innerWidth"), "unexpected page overflow"
        assert not errors, errors
        print("Browser smoke: desktop, 24 cars, map, telemetry, Q&A, comparison, replay, CSV, mobile viewport passed.")
        browser.close()


if __name__ == "__main__":
    main()
