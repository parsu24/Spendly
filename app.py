import sqlite3

from flask import Flask, redirect, render_template, request, url_for
from werkzeug.security import generate_password_hash

from database.db import get_db, init_db, seed_db

app = Flask(__name__)


# ------------------------------------------------------------------ #
# Startup                                                            #
# ------------------------------------------------------------------ #

# Build the schema and load development data before any request is served.
# Both calls are idempotent, so the reloader running this twice in debug
# mode is harmless.
with app.app_context():
    init_db()
    seed_db()


# ------------------------------------------------------------------ #
# Routes                                                              #
# ------------------------------------------------------------------ #

@app.route("/")
def landing():
    return render_template("landing.html")


# Shown for a duplicate address. Named because two separate paths below reach
# it — the pre-check and the constraint — and they must say the same thing.
EMAIL_TAKEN = "An account with that email already exists."


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "GET":
        return render_template("register.html")

    name = request.form.get("name", "").strip()
    # Lowercased on the way in: SQLite compares TEXT case-sensitively, so
    # without this Demo@spendly.com and demo@spendly.com would satisfy the
    # UNIQUE constraint separately and become two accounts.
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")   # never strip a password

    def reject(message):
        """Re-render the form with the fields still filled in.

        The password is deliberately left out — retyping it is the smaller
        cost, and it keeps the plain value out of the rendered HTML.
        """
        return render_template("register.html", error=message, name=name, email=email)

    # The template's `required` and type="email" attributes are a convenience
    # for the browser, not a control: anything can POST straight to this route,
    # so every rule is checked again here.
    local, _, domain = email.partition("@")

    if not name or not email or not password:
        return reject("Please fill in every field.")
    if not local or "." not in domain.strip("."):
        return reject("Please enter a valid email address.")
    if len(password) < 8:
        return reject("Password must be at least 8 characters.")

    conn = get_db()
    try:
        existing = conn.execute(
            "SELECT id FROM users WHERE email = ?", (email,)
        ).fetchone()
        if existing:
            return reject(EMAIL_TAKEN)

        try:
            conn.execute(
                "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
                (name, email, generate_password_hash(password)),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            # The SELECT above handles the ordinary case with a readable
            # message. This catches the narrow window where a second submit of
            # the same address lands between that check and this insert — the
            # UNIQUE constraint is what makes losing that race harmless.
            conn.rollback()
            return reject(EMAIL_TAKEN)
    finally:
        # `with get_db() as conn` commits but does not close; see the get_db()
        # docstring. Closing by hand is the only way to release the file.
        conn.close()

    # No session yet — logging the new account in arrives with Step 3.
    return redirect(url_for("login", registered=1))


@app.route("/login")
def login():
    return render_template("login.html")


@app.route("/terms")
def terms():
    return render_template("terms.html")


@app.route("/privacy")
def privacy():
    return render_template("privacy.html")


# ------------------------------------------------------------------ #
# Placeholder routes — students will implement these                  #
# ------------------------------------------------------------------ #

@app.route("/logout")
def logout():
    return "Logout — coming in Step 3"


@app.route("/profile")
def profile():
    return "Profile page — coming in Step 4"


@app.route("/expenses/add")
def add_expense():
    return "Add expense — coming in Step 7"


@app.route("/expenses/<int:id>/edit")
def edit_expense(id):
    return "Edit expense — coming in Step 8"


@app.route("/expenses/<int:id>/delete")
def delete_expense(id):
    return "Delete expense — coming in Step 9"


if __name__ == "__main__":
    app.run(debug=True, port=5001)
