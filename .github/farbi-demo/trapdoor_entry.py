import os

from flask import flash, redirect, render_template, request, session
from flask_login import current_user, login_user
from sqlalchemy import func, or_

from application import LoginForm, RegistrationForm, User, app, db

# Demo-only compatibility layer for the temporary reverse tunnel. Persistence,
# password hashing and role checks still use FARBI's real User model/PostgreSQL.
app.config["WTF_CSRF_ENABLED"] = False
app.config["PREFERRED_URL_SCHEME"] = "https"

# Fresh host-only cookies for the v4 public demo hostname. The deployment is
# only considered healthy after Chromium stores this cookie and opens protected
# pages with it.
app.config["SESSION_COOKIE_NAME"] = "farbi_demo_session_v4"
app.config["SESSION_COOKIE_DOMAIN"] = None
app.config["SESSION_COOKIE_PATH"] = "/"
app.config["SESSION_COOKIE_SECURE"] = True
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["REMEMBER_COOKIE_NAME"] = "farbi_demo_remember_v4"
app.config["REMEMBER_COOKIE_DOMAIN"] = None
app.config["REMEMBER_COOKIE_PATH"] = "/"
app.config["REMEMBER_COOKIE_SECURE"] = True
app.config["REMEMBER_COOKIE_HTTPONLY"] = True
app.config["REMEMBER_COOKIE_SAMESITE"] = "Lax"


@app.after_request
def demo_no_cache(response):
    # Prevent an intermediary/browser from reusing an anonymous index or auth
    # response immediately after the session changes.
    if request.path in {"/", "/login", "/register"} or request.path.startswith(("/profile", "/designer", "/admin")):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


def demo_register():
    form = RegistrationForm()
    if request.method == "GET" and current_user.is_authenticated:
        return redirect("/", code=302)

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
            return redirect("/", code=302)

    return render_template("register.html", form=form)


def demo_login():
    form = LoginForm()
    if request.method == "GET" and current_user.is_authenticated:
        return redirect("/", code=302)

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
            session.clear()
            login_user(user, remember=bool(request.form.get("remember")), force=True)
            session["auth_version"] = int(user.auth_version or 1)
            session["farbi_demo_role"] = (
                "admin" if user.is_admin else "designer" if user.is_designer else "customer"
            )
            return redirect("/", code=302)
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

PUBLIC_HOST = os.environ.get("FARBI_PUBLIC_HOST", "farbi-demo-otler17-v4.trapdoor.sh")
INTERNAL_HOST = "localhost:8000"


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
