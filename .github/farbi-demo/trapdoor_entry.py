import os

from flask import flash, redirect, render_template, request, session
from flask_login import current_user, login_user
from sqlalchemy import func, or_

from application import LoginForm, RegistrationForm, User, app, db

# Demo-only compatibility layer for the temporary reverse tunnel. Persistence,
# password hashing and role checks still use FARBI's real User model/PostgreSQL.
app.config["WTF_CSRF_ENABLED"] = False
app.config["PREFERRED_URL_SCHEME"] = "https"


def demo_register():
    form = RegistrationForm()
    if current_user.is_authenticated:
        return redirect("/", code=302)

    if request.method == "POST":
        username = (request.form.get("username") or "").strip().lower()
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        confirmation = request.form.get("confirm_password") or ""
        app.logger.warning(
            "DEMO_REGISTER endpoint=%s keys=%s username=%s email=%s",
            request.endpoint,
            sorted(request.form.keys()),
            username,
            email,
        )
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
            app.logger.warning("DEMO_REGISTER rejected reason=%s", error)
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
            login_user(user, force=True)
            session["auth_version"] = int(user.auth_version or 1)
            app.logger.warning("DEMO_REGISTER success user_id=%s", user.id)
            return redirect("/", code=302)

    return render_template("register.html", form=form)


def demo_login():
    form = LoginForm()
    if current_user.is_authenticated:
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
            "DEMO_LOGIN endpoint=%s keys=%s identifier=%s found=%s password_ok=%s archived=%s",
            request.endpoint,
            sorted(request.form.keys()),
            identifier,
            bool(user),
            password_ok,
            archived,
        )

        if user and password_ok and not archived:
            login_user(user, remember=bool(request.form.get("remember")), force=True)
            session["auth_version"] = int(user.auth_version or 1)
            app.logger.warning("DEMO_LOGIN success user_id=%s session_user=%s", user.id, session.get("_user_id"))
            return redirect("/", code=302)
        flash("Invalid credentials.", "danger")

    return render_template("login.html", form=form)


# Resolve endpoints from the URL map instead of assuming their names. This also
# guards against endpoint renames in the restored source bundle.
login_endpoints = [rule.endpoint for rule in app.url_map.iter_rules() if rule.rule == "/login"]
register_endpoints = [rule.endpoint for rule in app.url_map.iter_rules() if rule.rule == "/register"]
if not login_endpoints or not register_endpoints:
    raise RuntimeError(f"FARBI auth routes missing login={login_endpoints} register={register_endpoints}")
for endpoint in login_endpoints:
    app.view_functions[endpoint] = demo_login
for endpoint in register_endpoints:
    app.view_functions[endpoint] = demo_register
app.logger.warning("DEMO_AUTH overrides login=%s register=%s", login_endpoints, register_endpoints)

PUBLIC_HOST = os.environ.get("FARBI_PUBLIC_HOST", "farbi-demo-otler17.trapdoor.sh")
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
