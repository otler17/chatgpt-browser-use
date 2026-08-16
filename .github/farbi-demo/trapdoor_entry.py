from flask import flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_user
from sqlalchemy import func, or_

from application import LoginForm, RegistrationForm, User, app, db

# This wrapper is used only by the temporary GitHub-hosted demo. It bypasses
# Flask-WTF validation on the two demo auth POSTs because the tunnel rewrites
# origin/host metadata. Password checks and persistence still use FARBI's real
# User model and PostgreSQL database.
app.config["WTF_CSRF_ENABLED"] = False
app.config["PREFERRED_URL_SCHEME"] = "https"


def demo_register():
    form = RegistrationForm()
    if current_user.is_authenticated:
        return redirect(url_for("index"))

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
            login_user(user)
            session["auth_version"] = int(user.auth_version or 1)
            flash("Demo registration successful.", "success")
            return redirect(url_for("index"))

    return render_template("register.html", form=form)


def demo_login():
    form = LoginForm()
    if current_user.is_authenticated:
        return redirect(url_for("index"))

    if request.method == "POST":
        identifier = (request.form.get("identifier") or "").strip()
        password = request.form.get("password") or ""
        user = User.query.filter(
            or_(
                func.lower(User.email) == func.lower(identifier),
                func.lower(User.username) == func.lower(identifier),
            )
        ).first()

        if user and user.check_password(password) and not user.is_archived:
            login_user(user, remember=bool(request.form.get("remember")))
            session["auth_version"] = int(user.auth_version or 1)
            return redirect(url_for("index"))
        flash("Invalid credentials.", "danger")

    return render_template("login.html", form=form)


app.view_functions["register"] = demo_register
app.view_functions["login"] = demo_login

PUBLIC_HOST = "farbi-otler17.trapdoor.sh"
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
