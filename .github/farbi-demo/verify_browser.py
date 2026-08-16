import json
import os
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from playwright.sync_api import sync_playwright

BASE = os.environ.get("FARBI_URL", "https://farbi-demo-otler17-v5.trapdoor.sh").rstrip("/")
PASSWORD = os.environ.get("DEMO_PASSWORD", "Password123")
ACCESS_PARAM = "farbi_access"


def token_from_url(raw_url):
    values = parse_qs(urlsplit(raw_url).query).get(ACCESS_PARAM)
    if not values or not values[0]:
        raise RuntimeError(f"missing {ACCESS_PARAM} in browser URL: {raw_url}")
    return values[0]


def with_token(path, token):
    parts = urlsplit(f"{BASE}{path}")
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode({ACCESS_PARAM: token}), ""))


def assert_protected(page, context, token, protected_path, label):
    # Simulate the user's restrictive/sandboxed browser: remove every cookie
    # immediately before the protected navigation. Authentication must come
    # only from the signed URL token.
    context.clear_cookies()
    response = page.goto(with_token(protected_path, token), wait_until="networkidle", timeout=60000)
    if response is None or response.status != 200:
        raise RuntimeError(
            f"{label}: cookieless protected page failed status={None if response is None else response.status}"
        )
    if "/login" in page.url:
        raise RuntimeError(f"{label}: cookieless browser redirected to login: {page.url}")
    if ACCESS_PARAM not in page.url:
        raise RuntimeError(f"{label}: protected URL lost signed access token: {page.url}")

    # The server-side HTML rewrite must preserve access on ordinary navigation
    # links too, otherwise a user would appear logged out after the next click.
    propagated = page.locator(f'a[href*="{ACCESS_PARAM}="]').count()
    if propagated < 1:
        raise RuntimeError(f"{label}: page contained no token-propagating links")
    print(
        f"COOKIELESS {label} protected page passed: {protected_path}; "
        f"propagated_links={propagated}; cookies_after={context.cookies(BASE)}"
    )


def login_and_check(browser, email, protected_path, role):
    context = browser.new_context()
    page = context.new_page()
    page.goto(f"{BASE}/login", wait_until="networkidle", timeout=60000)
    page.locator('input[name="identifier"]').fill(email)
    password = page.locator('input[name="password"]')
    password.fill(PASSWORD)
    password.press("Enter")
    page.wait_for_load_state("networkidle", timeout=60000)

    token = token_from_url(page.url)

    # Delete all cookies and reload the exact post-login URL. If the browser
    # depends on Flask's cookie, this reload would immediately become anonymous.
    context.clear_cookies()
    response = page.reload(wait_until="networkidle", timeout=60000)
    if response is None or response.status != 200 or "/login" in page.url:
        raise RuntimeError(f"{role}: post-login page failed after clearing cookies: {page.url}")

    assert_protected(page, context, token, protected_path, role)

    # Also verify the one-click role entry point, useful when a sandbox refuses
    # the normal cookie mechanism completely.
    context.clear_cookies()
    response = page.goto(f"{BASE}/demo-access/{role}", wait_until="networkidle", timeout=60000)
    if response is None or response.status != 200:
        raise RuntimeError(f"{role}: demo-access entry failed")
    magic_token = token_from_url(page.url)
    assert_protected(page, context, magic_token, protected_path, f"{role}-magic")
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
    manifest["cookieless_chromium_role_logins_e2e"] = "passed"
    manifest["cookie_dependency"] = "none for demo access"
    manifest["demo_access_param"] = ACCESS_PARAM
    manifest["demo_access_routes"] = {
        "customer": "/demo-access/customer",
        "designer": "/demo-access/designer",
        "admin": "/demo-access/admin",
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print("Cookieless Chromium browser verification recorded in manifest")


if __name__ == "__main__":
    main()
