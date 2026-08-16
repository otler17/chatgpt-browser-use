import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

from application import User, app

BASE = os.environ.get("FARBI_URL", "https://farbi-demo-otler17.trapdoor.sh").rstrip("/")
PASSWORD = os.environ.get("DEMO_PASSWORD", "Password123")
TIMEOUT = 30
EXPECTED_SESSION_COOKIE = "farbi_demo_session_v3"


def url(path):
    return urljoin(BASE + "/", path.lstrip("/"))


def require_status(response, expected=200, label="request"):
    if response.status_code != expected:
        raise RuntimeError(
            f"{label} failed: {response.status_code} {response.url}; body={response.text[:500]!r}"
        )


def check_public(path):
    response = requests.get(url(path), timeout=TIMEOUT, allow_redirects=False)
    require_status(response, 200, f"public {path}")
    print(f"public {path} -> 200")
    return response


def login(email, label):
    session = requests.Session()
    # Reproduce a real tester who may still have Flask's old default `session`
    # cookie from one of the earlier ephemeral deployments on this same host.
    host = urlparse(BASE).hostname
    session.cookies.set("session", "stale-legacy-demo-cookie", domain=host, path="/")
    require_status(session.get(url("/login"), timeout=TIMEOUT), 200, f"{label} login form")
    response = session.post(
        url("/login"),
        data={"identifier": email, "password": PASSWORD, "submit": "Login"},
        timeout=TIMEOUT,
        allow_redirects=True,
    )
    require_status(response, 200, f"{label} login")
    cookie_names = sorted(session.cookies.keys())
    if EXPECTED_SESSION_COOKIE not in cookie_names:
        raise RuntimeError(
            f"{label} login did not issue {EXPECTED_SESSION_COOKIE}; cookies={cookie_names}"
        )
    print(f"{label} login POST -> 200; cookies={cookie_names}")
    return session


def check_authenticated(session, path, label):
    response = session.get(url(path), timeout=TIMEOUT, allow_redirects=False)
    require_status(response, 200, f"{label} {path}")
    print(f"{label} {path} -> 200")


def verify_signup():
    session = requests.Session()
    require_status(session.get(url("/register"), timeout=TIMEOUT), 200, "signup form")
    unique = os.environ.get("GITHUB_RUN_ID", "local")
    username = f"signup{unique}"
    email = f"signup{unique}@example.com"
    response = session.post(
        url("/register"),
        data={
            "username": username,
            "email": email,
            "password": PASSWORD,
            "confirm_password": PASSWORD,
            "submit": "Register",
        },
        timeout=TIMEOUT,
        allow_redirects=True,
    )
    require_status(response, 200, "signup")
    if EXPECTED_SESSION_COOKIE not in session.cookies.keys():
        raise RuntimeError(
            f"signup did not issue {EXPECTED_SESSION_COOKIE}; cookies={sorted(session.cookies.keys())}"
        )
    check_authenticated(session, "/profile/edit", "new customer")
    with app.app_context():
        created = User.query.filter_by(email=email).one_or_none()
        if created is None or not created.check_password(PASSWORD):
            raise RuntimeError("new signup was not persisted correctly in PostgreSQL")
    print(f"signup persisted -> {email}")


def main():
    design_ids = [
        int(value)
        for value in Path("instance/demo_design_ids.txt").read_text(encoding="utf-8").split(",")
        if value
    ]
    if len(design_ids) != 6:
        raise RuntimeError(f"expected 6 demo designs, got {design_ids}")

    for path in ("/", "/browse", "/designers", "/cart", "/login", "/register", "/profile/designer_seed"):
        check_public(path)
    for design_id in design_ids:
        check_public(f"/design/{design_id}")
    check_public("/uploads/images/design_previews/demo_planter_thumb.jpg")

    customer = login("customer_seed@example.com", "customer")
    check_authenticated(customer, "/profile/customer_seed", "customer")
    check_authenticated(customer, "/profile/edit", "customer")
    check_authenticated(customer, "/order_history", "customer")
    check_authenticated(customer, "/cart", "customer")

    designer = login("designer_seed@example.com", "designer")
    check_authenticated(designer, "/designer/dashboard", "designer")
    check_authenticated(designer, "/profile/designer_seed", "designer")
    check_authenticated(designer, "/profile/edit", "designer")

    admin = login("admin_seed@example.com", "admin")
    for path in ("/admin", "/admin/stl_library", "/admin/orders", "/admin/users", "/admin/settings"):
        check_authenticated(admin, path, "admin")

    verify_signup()

    manifest = {
        "origin": BASE,
        "run_id": os.environ.get("GITHUB_RUN_ID"),
        "published_at": datetime.now(timezone.utc).isoformat(),
        "database": "PostgreSQL 16",
        "redis": "Redis 7",
        "auth_routes": {"signin": "/login", "signup": "/register"},
        "session_cookie": EXPECTED_SESSION_COOKIE,
        "demo_password": PASSWORD,
        "demo_accounts": {
            "customer": {"email": "customer_seed@example.com", "username": "customer_seed"},
            "designer": {"email": "designer_seed@example.com", "username": "designer_seed"},
            "admin": {"email": "admin_seed@example.com", "username": "admin_seed"},
        },
        "dummy_data": {
            "products": 6,
            "reviews": 3,
            "completed_orders": 2,
            "categories": ["Home & Living", "Decor", "Accessories", "Toys & Games"],
        },
        "demo_design_ids": design_ids,
        "verified_pages": [
            "/",
            "/browse",
            "/designers",
            "/cart",
            "/login",
            "/register",
            "/profile/customer_seed",
            "/profile/designer_seed",
            "/profile/edit",
            "/order_history",
            "/designer/dashboard",
            "/admin",
            "/admin/stl_library",
            "/admin/orders",
            "/admin/users",
            "/admin/settings",
            "/design/<all six demo ids>",
            "/uploads/images/design_previews/demo_planter_thumb.jpg",
        ],
        "stale_cookie_login_e2e": "passed",
        "signup_e2e": "passed",
        "role_logins_e2e": "passed",
    }
    Path("../farbi-demo-manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
