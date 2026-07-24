import os
import sqlite3
from datetime import date

from flask import Flask, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from database.db import format_inr, get_db, init_db, seed_db, to_local

app = Flask(__name__)

# Signs the session cookie — without it Flask refuses to touch `session`.
# The fallback keeps development frictionless; a real deployment must set
# SECRET_KEY in the environment so cookies cannot be forged.
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-change-me")

# Rupee formatting lives in exactly one place. Templates write `{{ value | inr }}`
# rather than building a "₹" string by hand, so Indian digit grouping stays
# correct everywhere and later steps inherit it for free.
app.jinja_env.filters["inr"] = format_inr


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
    # Guards both methods: someone already signed in has no reason to open the
    # form, and no reason to be able to POST past it either.
    if session.get("user_id"):
        return redirect(url_for("profile"))

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


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        # Already signed in — no reason to show the form again.
        if session.get("user_id"):
            return redirect(url_for("profile"))
        return render_template("login.html")

    # Normalised the same way registration stores it, so an account created as
    # demo@spendly.com signs in as DEMO@Spendly.com too.
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")   # never strip a password

    conn = get_db()
    try:
        user = conn.execute(
            "SELECT id, name, password_hash FROM users WHERE email = ?", (email,)
        ).fetchone()
    finally:
        conn.close()

    # One message for both an unknown email and a wrong password: telling them
    # apart would reveal which addresses have accounts. check_password_hash is
    # the only correct check — the hash is never compared in SQL.
    if user is None or not check_password_hash(user["password_hash"], password):
        return render_template(
            "login.html",
            error="Incorrect email or password.",
            email=email,
        )

    session["user_id"] = user["id"]
    session["name"] = user["name"]
    # Signing in drops you on your own page, not back on the marketing copy.
    return redirect(url_for("profile"))


@app.route("/profile")
def profile():
    # The first route that requires a signed-in user. Every logged-in feature
    # from here on repeats this shape: read the identity from the session, and
    # scope every query to it — never to anything the visitor can type.
    user_id = session.get("user_id")
    if not user_id:
        return redirect(url_for("login"))

    conn = get_db()
    try:
        user = conn.execute(
            "SELECT name, email, created_at FROM users WHERE id = ?", (user_id,)
        ).fetchone()

        if user is None:
            # A cookie left over from a database that has since been rebuilt.
            # Clearing it turns a confusing half-empty page into a fresh login.
            session.clear()
            return redirect(url_for("login"))

        summary = conn.execute(
            "SELECT COUNT(*) AS count, COALESCE(SUM(amount), 0) AS total"
            "  FROM expenses WHERE user_id = ?",
            (user_id,),
        ).fetchone()

        # strftime('%Y-%m', date) reduces the stored 'YYYY-MM-DD' to its month,
        # which is cheaper to get right than hand-rolling a month-end boundary.
        month_total = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM expenses"
            "  WHERE user_id = ? AND strftime('%Y-%m', date) = ?",
            (user_id, date.today().strftime("%Y-%m")),
        ).fetchone()[0]

        breakdown = conn.execute(
            "SELECT category, SUM(amount) AS total FROM expenses"
            "  WHERE user_id = ? GROUP BY category ORDER BY total DESC",
            (user_id,),
        ).fetchall()
    finally:
        # `with get_db() as conn` commits but does not close; see the get_db()
        # docstring. Closing by hand is the only way to release the file.
        conn.close()

    # Bars are measured against the largest category rather than the total, so
    # the top one fills its track and the rest stay readable next to it.
    largest = breakdown[0]["total"] if breakdown else 0
    categories = [
        {
            "name": row["category"],
            "total": row["total"],
            "width": round(row["total"] / largest * 100, 1) if largest else 0,
        }
        for row in breakdown
    ]

    return render_template(
        "profile.html",
        user=user,
        # created_at is stored UTC; to_local() is what keeps an IST reader from
        # seeing a join date five and a half hours early.
        member_since=to_local(user["created_at"]).strftime("%d %B %Y"),
        total=summary["total"],
        count=summary["count"],
        month_total=month_total,
        categories=categories,
        top_category=categories[0]["name"] if categories else None,
    )


@app.route("/terms")
def terms():
    return render_template("terms.html")


@app.route("/privacy")
def privacy():
    return render_template("privacy.html")


@app.route("/logout")
def logout():
    # Drop every key, so this is harmless when no one is signed in.
    session.clear()
    return redirect(url_for("landing"))


# ------------------------------------------------------------------ #
# Placeholder routes — students will implement these                  #
# ------------------------------------------------------------------ #


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
