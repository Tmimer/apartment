import os
import re
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

import pytest
from playwright.sync_api import sync_playwright, expect

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARTIFACT_SCREENSHOT_DIR = (
    r"C:\Users\tamir\.gemini\antigravity\brain\f49d9cbc-680d-44bc-89a6-0d20f5a1d651\e2e_screenshots"
)


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _wait_for_server(base_url: str, timeout_sec: float = 20.0) -> None:
    deadline = time.time() + timeout_sec
    last_err = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{base_url}/health", timeout=2.0) as resp:
                if resp.status == 200:
                    return
        except Exception as err:
            last_err = err
            time.sleep(0.25)
    raise RuntimeError(f"Server at {base_url} failed to become healthy within {timeout_sec}s: {last_err}")


@pytest.fixture(scope="function")
def live_hub_server():
    """Boots plants_app.py against an isolated temporary SQLite database on a free port."""
    port = _find_free_port()
    base_url = f"http://127.0.0.1:{port}"
    tmp_dir = tempfile.mkdtemp(prefix="hub_e2e_")
    db_path = os.path.join(tmp_dir, "e2e_hub.db").replace("\\", "/")
    log_path = os.path.join(tmp_dir, "server.log")

    env = os.environ.copy()
    env["PORT"] = str(port)
    env["DATABASE_URL"] = f"sqlite:///{db_path}"
    env["GEMINI_API_KEY"] = ""
    env["PYTHONUTF8"] = "1"

    log_file = open(log_path, "w", encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, os.path.join(ROOT_DIR, "plants_app.py")],
        cwd=ROOT_DIR,
        env=env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
    )
    try:
        _wait_for_server(base_url)
        yield base_url, tmp_dir
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=6)
        except subprocess.TimeoutExpired:
            proc.kill()
        log_file.close()
        for root, dirs, files in os.walk(tmp_dir, topdown=False):
            for fname in files:
                try:
                    os.remove(os.path.join(root, fname))
                except OSError:
                    pass
            for dname in dirs:
                try:
                    os.rmdir(os.path.join(root, dname))
                except OSError:
                    pass
        try:
            os.rmdir(tmp_dir)
        except OSError:
            pass


def _assert_no_horizontal_overflow(page, label: str) -> None:
    overflow = page.evaluate(
        "() => ({ scrollWidth: document.documentElement.scrollWidth, clientWidth: document.documentElement.clientWidth })"
    )
    assert overflow["scrollWidth"] <= overflow["clientWidth"] + 2, (
        f"Horizontal overflow at {label}: scrollWidth={overflow['scrollWidth']} > clientWidth={overflow['clientWidth']}"
    )


def _save_screenshot(page, name: str) -> None:
    try:
        os.makedirs(ARTIFACT_SCREENSHOT_DIR, exist_ok=True)
        page.screenshot(path=os.path.join(ARTIFACT_SCREENSHOT_DIR, name), full_page=False)
    except Exception:
        pass


@pytest.mark.parametrize(
    "viewport_name,viewport",
    [
        ("desktop_1440x900", {"width": 1440, "height": 900}),
        ("mobile_s22_412x915", {"width": 412, "height": 915}),
    ],
)
def test_e2e_shared_apartment_hub_desktop_and_mobile(live_hub_server, viewport_name, viewport):
    base_url, tmp_dir = live_hub_server

    console_errors = []
    page_errors = []
    server_500s = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport=viewport,
            accept_downloads=True,
        )
        page = context.new_page()

        # Auto-accept alert/confirm dialogs during delete/settle E2E actions
        page.on("dialog", lambda d: d.accept())
        page.on(
            "console",
            lambda msg: console_errors.append(msg.text)
            if msg.type == "error" and "status of 4" not in msg.text
            else None,
        )
        page.on("pageerror", lambda exc: page_errors.append(str(exc)))
        page.on(
            "response",
            lambda res: server_500s.append(f"{res.status} {res.url}") if res.status >= 500 else None,
        )

        # 1. Authenticate via login endpoint & load hub
        login_res = page.request.post(f"{base_url}/api/auth/login", data={"passcode": "apartment123"})
        assert login_res.status == 200

        page.goto(f"{base_url}/?tab=plants", wait_until="networkidle")
        expect(page.locator("#tab-plants")).to_have_class(re.compile(r"active"))
        _assert_no_horizontal_overflow(page, f"{viewport_name}-plants")

        # 2. Verify existing tabs (Plants, Status Note, Meals, Maintenance, Dates & Movie Watchlist)
        page.locator("#fridge-magnet-bar").click()
        expect(page.locator("#fridge-note-modal")).to_have_class(re.compile(r"open"))
        page.locator("#fridge-note-input").fill(f"[{viewport_name}] קונה עגבניות at AM:PM")
        page.locator("#fridge-note-modal .modal-footer .btn-primary").click()
        expect(page.locator("#fridge-note-modal")).not_to_have_class(re.compile(r"open"))

        page.locator("#nav-btn-meals").click()
        expect(page.locator("#tab-meals")).to_have_class(re.compile(r"active"))
        _assert_no_horizontal_overflow(page, f"{viewport_name}-meals")

        page.locator("#nav-btn-maintenance").click()
        expect(page.locator("#tab-maintenance")).to_have_class(re.compile(r"active"))
        _assert_no_horizontal_overflow(page, f"{viewport_name}-maintenance")

        page.locator("#nav-btn-dates").click()
        expect(page.locator("#tab-dates")).to_have_class(re.compile(r"active"))
        page.locator("#dates-subnav-movies").click()
        expect(page.locator("#dates-view-movies")).to_be_visible()
        page.locator("#btn-movie-status-watchlist").click()
        _assert_no_horizontal_overflow(page, f"{viewport_name}-dates-movies")

        # 3. Switch to Groceries Tab & verify Smart Auto-detect default + Bilingual Items + Walking Order
        page.locator("#nav-btn-groceries").click()
        expect(page.locator("#tab-groceries")).to_have_class(re.compile(r"active"))
        assert page.locator("#grocery-category-select").input_value() == ""

        # Wait for initial seed/meals load
        page.wait_for_selector("#meal-to-cart-quick-bar .meal-cart-chip")

        # Add clean Hebrew & English dictionary items via Smart Auto-detect
        if viewport_name == "desktop_1440x900":
            items_to_add = ["עגבניות שרי", "קוטג'", "Olive Oil"]
        else:
            items_to_add = ["מלפפון", "חלב", "סבון כלים"]

        for name in items_to_add:
            page.locator("#grocery-quick-input").fill(name)
            with page.expect_response(lambda r: "/groceries/api/items" in r.url and r.request.method == "POST"):
                page.locator("#btn-grocery-add").click()
            expect(page.locator("#grocery-items-container")).to_contain_text(name)

        # Ensure delayed autocomplete debounce does not re-open dropdown after submit
        page.wait_for_timeout(350)
        expect(page.locator("#grocery-autocomplete-list")).to_be_hidden()

        expect(page.locator("#grocery-items-container .grocery-category-header", has_text="Produce")).to_be_visible()
        expect(page.locator("#grocery-items-container .grocery-category-header", has_text="Dairy")).to_be_visible()

        # Verify Supermarket Walking-Order grouping order in DOM (Produce appears before Dairy/Eggs)
        headers_text = page.locator("#grocery-items-container .grocery-category-header").all_inner_texts()
        produce_idx = next(i for i, t in enumerate(headers_text) if "produce" in t.lower())
        dairy_idx = next(i for i, t in enumerate(headers_text) if "dairy" in t.lower())
        assert produce_idx < dairy_idx

        # Verify RTL/bidi alignment attributes on mixed Hebrew/English item names
        first_bidi = page.locator("#grocery-items-container .grocery-name.bidi-text").first
        assert first_bidi.get_attribute("dir") == "auto"
        assert first_bidi.evaluate("el => getComputedStyle(el).unicodeBidi") in ("plaintext", "isolate")

        # Toggle Solo Shopper "Hide/Dim Produce" -> banner hides Produce, tap to expand dimmed
        page.locator("#btn-solo-shopper-toggle").click()
        expect(page.locator("#btn-solo-shopper-toggle")).to_have_class(re.compile(r"active"))
        dimmed_banner = page.locator("#grocery-items-container .produce-dimmed-banner")
        expect(dimmed_banner).to_be_visible()
        dimmed_banner.click()
        dimmed_opacity = page.locator("#grocery-items-container .grocery-item-card").first.evaluate(
            "el => parseFloat(getComputedStyle(el).opacity)"
        )
        assert dimmed_opacity < 0.75
        page.locator("#btn-solo-shopper-toggle").click()

        # 1-Click Meal-to-Cart injection
        page.locator("#meal-to-cart-quick-bar .meal-cart-chip").first.click()
        expect(page.locator("#meal-to-cart-modal")).to_have_class(re.compile(r"open"))
        mtc_checks = page.locator("#mtc-ingredients-list .mtc-ing-chk")
        if mtc_checks.count() > 1:
            mtc_checks.first.uncheck()
        page.locator("#meal-to-cart-modal .modal-footer .btn-primary").click()
        expect(page.locator("#meal-to-cart-modal")).not_to_have_class(re.compile(r"open"))

        _assert_no_horizontal_overflow(page, f"{viewport_name}-groceries")
        _save_screenshot(page, f"{viewport_name}_groceries.png")

        # 4. Brain Dump Local Fallback ("milk, eggs, and 85 for groceries")
        page.locator("#brain-dump-input").fill("milk, eggs, and 85 for groceries")
        page.locator("#btn-brain-dump-submit").click()
        expect(page.locator("#brain-dump-result-banner")).to_be_visible()
        expect(page.locator("#brain-dump-result-banner")).to_contain_text("85")

        # 5. Simulated Receipt Review via Offline Receipt Text with מבצע discount & MIKUSH_100 produce
        page.locator(".btn-scan-receipt-cta").click()
        expect(page.locator("#receipt-scanner-modal")).to_have_class(re.compile(r"open"))
        page.locator("#receipt-text-fallback-details summary").click()
        page.locator("#receipt-text-input").fill(
            "שופרסל\nעגבניות 12.90\nמבצע עגבניות -3.00\nקוטג' 6.50\n"
        )
        page.locator("#btn-parse-receipt-text").click()
        expect(page.locator("#receipt-review-container")).to_be_visible()
        expect(page.locator("#receipt-items-list")).to_contain_text("מבצע עגבניות")
        expect(page.locator("#rec-sum-mikush")).to_contain_text("9.90")
        expect(page.locator("#rec-sum-5050")).to_contain_text("6.50")

        # Verify modal scrolling metrics fit inside viewport on mobile & desktop
        sheet_box = page.locator("#receipt-scanner-modal .modal-sheet").bounding_box()
        assert sheet_box is not None and sheet_box["height"] <= viewport["height"]
        _save_screenshot(page, f"{viewport_name}_receipt_review.png")

        page.locator("#btn-commit-receipt").click()
        expect(page.locator("#receipt-scanner-modal")).not_to_have_class(re.compile(r"open"))

        # 6. Ledger Subview: Recurring Bill Preset, Breakdown Drawer, CSV Export, Splitwise CSV Import & Settle-Up
        page.locator("#shop-subnav-ledger").click()
        expect(page.locator("#groceries-subview-ledger")).to_be_visible()
        _assert_no_horizontal_overflow(page, f"{viewport_name}-ledger")

        # 1-tap Recurring Bill preset (Gas / Vaad Bayit) and confirm wrapped chips fit viewport without horizontal clip
        preset_chips = page.locator("#recurring-bill-presets-bar .staple-chip")
        assert preset_chips.count() == 7
        for i in range(preset_chips.count()):
            chip_box = preset_chips.nth(i).bounding_box()
            assert chip_box is not None and chip_box["x"] >= 0 and (chip_box["x"] + chip_box["width"]) <= viewport["width"]

        page.locator("#recurring-bill-presets-bar button", has_text="Gas / Vaad Bayit").click()
        expect(page.locator("#ledger-expense-modal")).to_have_class(re.compile(r"open"))
        page.locator("#tx-input-amount").fill("300")
        page.locator("#ledger-expense-modal .modal-footer .btn-primary").click()
        expect(page.locator("#ledger-expense-modal")).not_to_have_class(re.compile(r"open"))

        # Verify Breakdown Drawer reflects Shared Groceries, Produce & Apartment Bills
        expect(page.locator("#ledger-breakdown-body")).to_contain_text("Shared Groceries")
        expect(page.locator("#ledger-breakdown-body")).to_contain_text("Produce")
        expect(page.locator("#ledger-breakdown-body")).to_contain_text("Apartment Bills")
        _save_screenshot(page, f"{viewport_name}_ledger.png")

        # Verify 1-click CSV Export download
        with page.expect_download() as dl_info:
            page.locator("#btn-export-ledger-csv").click()
        dl = dl_info.value
        assert dl.suggested_filename.endswith(".csv")

        # Splitwise CSV import
        csv_path = os.path.join(tmp_dir, f"splitwise_{viewport_name}.csv")
        with open(csv_path, "w", encoding="utf-8") as f:
            f.write("Date,Description,Category,Cost,Currency,Tamir,Mikush\n")
            f.write("2026-11-10,Arnona Test,Utilities,200.00,ILS,100.00,-100.00\n")

        page.locator("#groceries-subview-ledger button", has_text="Import Splitwise CSV").click()
        expect(page.locator("#splitwise-import-modal")).to_have_class(re.compile(r"open"))
        page.locator("#splitwise-csv-file").set_input_files(csv_path)
        page.locator("#splitwise-import-modal .modal-footer .btn-primary").click()
        expect(page.locator("#splitwise-import-modal")).not_to_have_class(re.compile(r"open"))

        # Mobile touch-target verification for action buttons in ledger/list
        if viewport_name == "mobile_s22_412x915":
            btn_box = page.locator("#ledger-transactions-list .btn-log-action").first.bounding_box()
            assert btn_box is not None and btn_box["width"] >= 32 and btn_box["height"] >= 32

        # Manual Settle-Up archiving
        page.locator("#groceries-subview-ledger button", has_text="Settle Up").click()
        expect(page.locator("#settle-up-modal")).to_have_class(re.compile(r"open"))
        page.locator("#settle-up-modal .modal-footer .btn-primary").click()
        expect(page.locator("#settle-up-modal")).not_to_have_class(re.compile(r"open"))
        expect(page.locator("#ledger-hero-headline")).to_contain_text("All Settled Up!")
        assert int(page.locator("#settlement-history-count").inner_text()) >= 1

        context.close()
        browser.close()

    assert not console_errors, f"Console errors ({viewport_name}): {console_errors}"
    assert not page_errors, f"Uncaught page errors ({viewport_name}): {page_errors}"
    assert not server_500s, f"HTTP 5xx errors ({viewport_name}): {server_500s}"
