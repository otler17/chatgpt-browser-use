import json
import os
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = os.environ.get("FARBI_URL", "https://farbi-demo-otler17-v4.trapdoor.sh").rstrip("/")
PASSWORD = os.environ.get("DEMO_PASSWORD", "Password123")
COOKIE_NAME = "farbi_demo_session_v4"


def login_and_check(browser, email, protected_path, label):
    context = browser.new_context()
    page = context.new_page()
    page.goto(f"{BASE}/login", wait_until="networkidle", timeout=60000)
    page.locator('input[name="identifier"]').fill(email)
    page.locator('input[name="password"]').fill(PASSWORD)
    page.locator('button[type="submit"], input[type="submit"]').first.click()
    page.wait_for_load_state("networkidle", timeout=60000)

    cookies = context.cookies(BASE)
    cookie_names = {cookie["name"] for cookie in cookies}
    if COOKIE_NAME not in cookie_names:
        raise RuntimeError(
            f"{label}: Chromium did not store {COOKIE_NAME}; cookies={cookies}; url={page.url}"
        )

    response = page.goto(f"{BASE}{protected_path}", wait_until="networkidle", timeout=60000)
    if response is None or response.status != 200:
        raise RuntimeError(
            f"{label}: protected page failed status={None if response is None else response.status}"
        )
    if "/login" in page.url:
        raise RuntimeError(f"{label}: Chromium was redirected back to login: {page.url}")

    print(
        f"BROWSER {label} login passed: cookie={COOKIE_NAME} "
        f"protected={protected_path} url={page.url}"
    )
    context.close()


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            login_and_check(browser, "customer_seed@example.com", "/profile/edit", "customer")
            login_and_check(browser, "designer_seed@example.com", "/designer/dashboard", "designer")
            login_and_check(browser, "admin_seed@example.com", "/admin", "admin")
        finally:
            browser.close()

    manifest_path = Path("../farbi-demo-manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["chromium_role_logins_e2e"] = "passed"
    manifest["browser_verified_cookie"] = COOKIE_NAME
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print("Chromium browser verification recorded in manifest")


if __name__ == "__main__":
    main()
