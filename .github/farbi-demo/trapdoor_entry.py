import json
import os
from html import escape
from urllib.parse import parse_qs, parse_qsl, urlencode, urlsplit, urlunsplit

from bs4 import BeautifulSoup
from flask import flash, g, make_response, render_template, request, session
from flask_login import current_user, login_user
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import func, or_

from application import LoginForm, RegistrationForm, User, app, db

# Demo-only compatibility layer for the temporary reverse tunnel. Persistence,
# password hashing and role checks still use FARBI's real User model/PostgreSQL.
app.config["WTF_CSRF_ENABLED"] = False
app.config["PREFERRED_URL_SCHEME"] = "https"

PUBLIC_HOST = os.environ.get("FARBI_PUBLIC_HOST", "farbi-demo-otler17-v5.trapdoor.sh")
INTERNAL_HOST = "localhost:8000"
ACCESS_PARAM = "farbi_access"
ACCESS_MAX_AGE = 8 * 60 * 60
ACCESS_SERIALIZER = URLSafeTimedSerializer(
    app.config["SECRET_KEY"], salt="farbi-demo-cookieless-v5"
)

# Normal cookies remain enabled for ordinary browsers, but v5 no longer relies
# on them. A signed URL token is propagated through links/forms/redirects and
# can authenticate every request even when a sandbox discards all cookies.
app.config["SESSION_COOKIE_NAME"] = "farbi_demo_session_v5"
app.config["SESSION_COOKIE_DOMAIN"] = None
app.config["SESSION_COOKIE_PATH"] = "/"
app.config["SESSION_COOKIE_SECURE"] = True
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["REMEMBER_COOKIE_NAME"] = "farbi_demo_remember_v5"
app.config["REMEMBER_COOKIE_DOMAIN"] = None
app.config["REMEMBER_COOKIE_PATH"] = "/"
app.config["REMEMBER_COOKIE_SECURE"] = True
app.config["REMEMBER_COOKIE_HTTPONLY"] = True
app.config["REMEMBER_COOKIE_SAMESITE"] = "Lax"


def make_access_token(user):
    return ACCESS_SERIALIZER.dumps(
        {"uid": int(user.id), "av": int(user.auth_version or 1)}
    )


def load_access_user(token):
    if not token:
        return None
    try:
        payload = ACCESS_SERIALIZER.loads(token, max_age=ACCESS_MAX_AGE)
        user = db.session.get(User, int(payload["uid"]))
    except (BadSignature, SignatureExpired, KeyError, TypeError, ValueError):
        return None
    if not user or user.is_archived:
        return None
    if int(user.auth_version or 1) != int(payload.get("av", 1)):
        return None
    return user


def token_from_request():
    token = request.args.get(ACCESS_PARAM)
    if token:
        return token
    # Same-origin fetch/XHR calls inherit auth from the current page URL through
    # the Referer header, so the original FARBI JavaScript does not need edits.
    referer = request.headers.get("Referer") or ""
    if referer:
        values = parse_qs(urlsplit(referer).query).get(ACCESS_PARAM)
        if values:
            return values[0]
    return None


def demo_access_before_request():
    token = token_from_request()
    user = load_access_user(token)
    g.farbi_access_token = token if user else None
    if user:
        # Flask-Login resolves current_user from g._login_user first. Installing
        # the user here makes every existing login_required/role check work
        # without any browser cookie.
        g._login_user = user


# Run before FARBI's existing before_request guards.
app.before_request_funcs.setdefault(None, []).insert(0, demo_access_before_request)


def add_access_to_url(raw_url, token):
    if not raw_url or not token:
        return raw_url
    if raw_url.startswith(("#", "mailto:", "tel:", "javascript:", "data:")):
        return raw_url
    parts = urlsplit(raw_url)
    if parts.scheme and parts.scheme not in {"http", "https"}:
        return raw_url
    if parts.netloc and parts.netloc.lower() not in {
        request.host.lower(),
        PUBLIC_HOST.lower(),
    }:
        return raw_url
    if parts.path.rstrip("/") == "/logout":
        return raw_url
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != ACCESS_PARAM]
    query.append((ACCESS_PARAM, token))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def client_navigate(raw_url, token, message="Signing you in…"):
    """Return HTTP 200 and let the browser navigate itself.

    Trapdoor follows upstream 302 responses internally, which hides the redirect
    URL from the real browser. A 200 response with both meta refresh and JS keeps
    navigation on the client side, so the signed token reaches the address bar
    even when cookies are blocked and the proxy consumes backend redirects.
    """
    target = add_access_to_url(raw_url, token)
    safe_target = escape(target, quote=True)
    js_target = json.dumps(target)
    body = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta http-equiv="cache-control" content="no-store">
<meta http-equiv="refresh" content="0;url={safe_target}">
<title>FARBI demo access</title>
</head>
<body data-farbi-target="{safe_target}">
<p>{escape(message)}</p>
<p><a href="{safe_target}">Continue to FARBI</a></p>
<script>window.location.replace({js_target});</script>
</body>
</html>"""
    response = make_response(body, 200)
    response.headers["X-Farbi-Demo-Target"] = target
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return response


@app.after_request
def demo_access_response(response):
    # Logout intentionally drops cookieless access instead of immediately
    # re-authenticating the user on the redirect target.
    token = None if request.path.rstrip("/") == "/logout" else getattr(g, "farbi_access_token", None)

    # Other FARBI routes may still emit redirects. If Trapdoor follows them
    # internally, the target still carries the signed token and remains auth'd.
    location = response.headers.get("Location")
    if token and location:
        response.headers["Location"] = add_access_to_url(location, token)

    content_type = response.headers.get("Content-Type", "")
    if token and "text/html" in content_type and response.get_data():
        soup = BeautifulSoup(response.get_data(as_text=True), "html.parser")
        for tag in soup.find_all(href=True):
            tag["href"] = add_access_to_url(tag.get("href"), token)
        for tag in soup.find_all(action=True):
            tag["action"] = add_access_to_url(tag.get("action"), token)
        for tag in soup.find_all(formaction=True):
            tag["formaction"] = add_access_to_url(tag.get("formaction"), token)
        response.set_data(str(soup))

    if request.path in {"/", "/login", "/register"} or request.path.startswith(("/profile", "/designer", "/admin")):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


def demo_register():
    form = RegistrationForm()
    if request.method == "GET" and current_user.is_authenticated:
        token = getattr(g, "farbi_access_token", None) or make_access_token(current_user)
        g.farbi_access_token = token
        return client_navigate("/", token, "Opening your FARBI account…")

    if request.method == "POST":
        username = (request.form.get("username") or "").strip().lower()
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        confirmation = request.form.get("confirm_password") or ""
        error = None

        if len(username) < 3:
            error = "Username must be at least 3 characters."
        elif "@" not in email:
            error = "Please enter a valid email address."
        elif len(password) < 8:
            error = "Password must be at least 8 characters."
        elif password != confirmation:
            error = "Passwords do not match."
        elif User.query.filter(func.lower(User.username) == username).first():
            error = "Username already exists."
        elif User.query.filter(func.lower(User.email) == email).first():
            error = "Email already exists."

        if error:
            flash(error, "danger")
        else:
            user = User(
                username=username,
                email=email,
                is_designer=False,
                email_verified=True,
            )
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            session.clear()
            login_user(user, force=True)
            session["auth_version"] = int(user.auth_version or 1)
            token = make_access_token(user)
            g.farbi_access_token = token
            return client_navigate("/", token, "Account created. Opening FARBI…")

    return render_template("register.html", form=form)


def demo_login():
    form = LoginForm()
    if request.method == "GET" and current_user.is_authenticated:
        token = getattr(g, "farbi_access_token", None) or make_access_token(current_user)
        g.farbi_access_token = token
        return client_navigate("/", token)

    if request.method == "POST":
        identifier = (request.form.get("identifier") or "").strip()
        password = request.form.get("password") or ""
        user = User.query.filter(
            or_(
                func.lower(User.email) == func.lower(identifier),
                func.lower(User.username) == func.lower(identifier),
            )
        ).first()
        password_ok = bool(user and user.check_password(password))
        archived = bool(user and user.is_archived)
        app.logger.warning(
            "DEMO_LOGIN endpoint=%s identifier=%s found=%s password_ok=%s archived=%s",
            request.endpoint,
            identifier,
            bool(user),
            password_ok,
            archived,
        )

        if user and password_ok and not archived:
            # Keep normal Flask-Login for conventional browsers, but the signed
            # URL access path below is sufficient on its own.
            session.clear()
            login_user(user, remember=bool(request.form.get("remember")), force=True)
            session["auth_version"] = int(user.auth_version or 1)
            session["farbi_demo_role"] = (
                "admin" if user.is_admin else "designer" if user.is_designer else "customer"
            )
            token = make_access_token(user)
            g.farbi_access_token = token
            return client_navigate("/", token)
        flash("Invalid credentials.", "danger")

    return render_template("login.html", form=form)


login_endpoints = [rule.endpoint for rule in app.url_map.iter_rules() if rule.rule == "/login"]
register_endpoints = [rule.endpoint for rule in app.url_map.iter_rules() if rule.rule == "/register"]
if not login_endpoints or not register_endpoints:
    raise RuntimeError(f"FARBI auth routes missing login={login_endpoints} register={register_endpoints}")
for endpoint in login_endpoints:
    app.view_functions[endpoint] = demo_login
for endpoint in register_endpoints:
    app.view_functions[endpoint] = demo_register
app.logger.warning("DEMO_AUTH overrides login=%s register=%s", login_endpoints, register_endpoints)


ROLE_EMAILS = {
    "customer": "customer_seed@example.com",
    "designer": "designer_seed@example.com",
    "admin": "admin_seed@example.com",
}


@app.get("/demo-access/<role>")
def demo_access_start(role):
    email = ROLE_EMAILS.get(role.lower())
    if not email:
        return "Unknown FARBI demo role", 404
    user = User.query.filter(func.lower(User.email) == email.lower()).first()
    if not user or user.is_archived:
        return "FARBI demo account unavailable", 503
    token = make_access_token(user)
    g.farbi_access_token = token
    return client_navigate("/", token, f"Opening FARBI as {role.lower()}…")


class TrapdoorPublicHost:
    def __init__(self, wrapped):
        self.wrapped = wrapped

    def __call__(self, environ, start_response):
        if environ.get("HTTP_HOST", "").lower() == INTERNAL_HOST:
            environ["HTTP_HOST"] = PUBLIC_HOST
            environ["SERVER_NAME"] = PUBLIC_HOST
            environ["SERVER_PORT"] = "443"
            environ["wsgi.url_scheme"] = "https"
        return self.wrapped(environ, start_response)


app.wsgi_app = TrapdoorPublicHost(app.wsgi_app)
