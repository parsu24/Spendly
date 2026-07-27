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


@app.route("/profile/edit", methods=["GET", "POST"])
def profile_edit():
    # No re-authentication here, deliberately. Changing a name or an email is
    # recoverable — you can simply change it back — so the current password is
    # not asked for. Changing the password and deleting the account are not
    # recoverable, and those routes do require it. The asymmetry is a choice,
    # not an omission.

    # Same guard /profile uses, and it runs first: `request.form` is never read
    # before the visitor's identity is known, because anything can POST straight
    # at this URL without ever loading the form.
    user_id = session.get("user_id")
    if not user_id:
        return redirect(url_for("login"))

    conn = get_db()
    try:
        user = conn.execute(
            "SELECT name, email FROM users WHERE id = ?", (user_id,)
        ).fetchone()

        if user is None:
            # A cookie left over from a database that has since been rebuilt.
            # Clearing it turns a confusing half-empty page into a fresh login.
            session.clear()
            return redirect(url_for("login"))

        if request.method == "GET":
            # Prefilled, so "save" without touching a field is a no-op rather
            # than a way to blank the account out.
            return render_template(
                "profile_edit.html", name=user["name"], email=user["email"]
            )

        name = request.form.get("name", "").strip()
        # Lowercased on the way in for the same reason registration does it:
        # SQLite compares TEXT case-sensitively, so without this an account
        # could be edited from demo@spendly.com to Demo@Spendly.com and slip
        # past the UNIQUE constraint as a second, distinct address.
        email = request.form.get("email", "").strip().lower()

        def reject(message):
            """Re-render the form with the submitted values still in place."""
            return render_template(
                "profile_edit.html", error=message, name=name, email=email
            )

        # The template's `required` and type="email" attributes are a
        # convenience for the browser, not a control, so every rule is checked
        # again here — using the same wording registration uses, because a
        # visitor should not have to learn two vocabularies for one mistake.
        local, _, domain = email.partition("@")

        if not name or not email:
            return reject("Please fill in every field.")
        if not local or "." not in domain.strip("."):
            return reject("Please enter a valid email address.")

        # `AND id != ?` is what makes this an edit rather than a registration:
        # your own row already holds your address, so without it saving the
        # form unchanged would report the email as taken against yourself.
        clash = conn.execute(
            "SELECT id FROM users WHERE email = ? AND id != ?", (email, user_id)
        ).fetchone()
        if clash:
            return reject(EMAIL_TAKEN)

        try:
            # Scoped to the session's id, never to anything the visitor can
            # type. created_at is deliberately absent from the SET list so
            # "Member since" survives an edit.
            conn.execute(
                "UPDATE users SET name = ?, email = ? WHERE id = ?",
                (name, email, user_id),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            # The SELECT above is advisory and covers the ordinary case with a
            # readable message; users.email UNIQUE is the actual enforcement,
            # and it is what catches a second account claiming this address
            # between that check and this update.
            conn.rollback()
            return reject(EMAIL_TAKEN)
    finally:
        # `with get_db() as conn` commits but does not close; see the get_db()
        # docstring. Closing by hand is the only way to release the file.
        conn.close()

    # Success path only. base.html renders session.name in the nav and login is
    # otherwise the only thing that sets it, so without this line the header
    # keeps showing the old name until the next sign-in. The stripped value is
    # the one stored, matching what just went into the database.
    session["name"] = name

    return redirect(url_for("profile", updated=1))


@app.route("/profile/password", methods=["GET", "POST"])
def profile_password():
    # Same guard /profile uses, and it runs first: `request.form` is never read
    # before the visitor's identity is known, because anything can POST straight
    # at this URL without ever loading the form.
    user_id = session.get("user_id")
    if not user_id:
        return redirect(url_for("login"))

    conn = get_db()
    try:
        # The hash is read for one purpose — verifying the current password
        # below. It is never handed to a template: nothing about the stored
        # credential belongs in rendered HTML.
        user = conn.execute(
            "SELECT password_hash FROM users WHERE id = ?", (user_id,)
        ).fetchone()

        if user is None:
            # A cookie left over from a database that has since been rebuilt.
            # Clearing it turns a confusing half-empty page into a fresh login.
            session.clear()
            return redirect(url_for("login"))

        if request.method == "GET":
            # No context at all: every field on this form is a password, so
            # there is nothing here worth prefilling.
            return render_template("profile_password.html")

        # None of the three is stripped. A leading or trailing space is part of
        # a password, and trimming it here would silently store something the
        # visitor cannot type back in.
        current_password = request.form.get("current_password", "")
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")

        def reject(message):
            """Re-render the form with the error and no field values.

            Unlike the edit form, nothing is carried back: all three inputs are
            passwords, and preserving even one would write a plain password
            into the HTML this response sends over the wire.
            """
            return render_template("profile_password.html", error=message)

        # The template's `required` attributes are a convenience for the
        # browser, not a control, so the same wording registration uses is
        # applied again here.
        if not current_password or not new_password or not confirm_password:
            return reject("Please fill in every field.")

        # Re-authentication comes before the shape checks on purpose: whatever
        # else is wrong with the submission, someone who cannot produce the
        # current password should be told exactly that and nothing else.
        #
        # And it says so specifically, unlike login's deliberately vague
        # "Incorrect email or password." — that message exists to stop a
        # stranger enumerating which addresses have accounts. Here the visitor
        # is already signed in as this account, so there is nothing left to
        # disclose and a precise message is simply kinder. Do not "fix" this
        # into the generic string.
        if not check_password_hash(user["password_hash"], current_password):
            return reject("Your current password is not correct.")

        # The same floor registration enforces (see register() above). A route
        # that let an existing account drop below it would make the rule
        # something you only have to satisfy once.
        if len(new_password) < 8:
            return reject("Password must be at least 8 characters.")
        # The confirmation field is the only defence against a typo in a value
        # nobody can see as they type it.
        if new_password != confirm_password:
            return reject("The new passwords do not match.")
        # Not a security rule, just an honest one: a "change" that changes
        # nothing is almost always a mistake at the keyboard.
        if new_password == current_password:
            return reject("Your new password must be different from your current one.")

        # Scoped to the session's id, never to anything the visitor can type.
        # No IntegrityError guard here, unlike the edit route: password_hash
        # carries no unique constraint, so there is no race to lose.
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (generate_password_hash(new_password), user_id),
        )
        conn.commit()
    finally:
        # `with get_db() as conn` commits but does not close; see the get_db()
        # docstring. Closing by hand is the only way to release the file.
        conn.close()

    # The session is deliberately left alone. Changing your own password is not
    # a reason to be signed out of the browser you changed it from, and
    # session["name"] still matches the row — the name did not change.
    return redirect(url_for("profile", password=1))


@app.route("/profile/delete", methods=["GET", "POST"])
def profile_delete():
    # Same guard /profile uses, and it runs first: `request.form` is never read
    # before the visitor's identity is known, because anything can POST straight
    # at this URL without ever loading the form.
    user_id = session.get("user_id")
    if not user_id:
        return redirect(url_for("login"))

    conn = get_db()
    try:
        # Read for one purpose — verifying the password below. As on the
        # change-password route, the stored credential is never handed to a
        # template.
        user = conn.execute(
            "SELECT password_hash FROM users WHERE id = ?", (user_id,)
        ).fetchone()

        if user is None:
            # A cookie left over from a database that has since been rebuilt.
            # Clearing it turns a confusing half-empty page into a fresh login.
            session.clear()
            return redirect(url_for("login"))

        # Computed before the method branch on purpose. The confirmation screen
        # needs it, but so does every rejected submit — putting this inside the
        # `GET` branch would leave `total` undefined the moment someone typed
        # the wrong password, turning a routine mistake into a 500.
        #
        # COALESCE is load-bearing for the same reason it is on /profile: an
        # account with no expenses sums to NULL, and `{{ None | inr }}` would
        # blow up inside format_inr rather than render "₹0".
        summary = conn.execute(
            "SELECT COUNT(*) AS count, COALESCE(SUM(amount), 0) AS total"
            "  FROM expenses WHERE user_id = ?",
            (user_id,),
        ).fetchone()

        if request.method == "GET":
            # Renders the confirmation and deletes nothing. A destructive action
            # behind a GET fires on a link prefetch or a passing crawler, with
            # nobody having clicked anything.
            return render_template(
                "profile_delete.html",
                count=summary["count"],
                total=summary["total"],
            )

        password = request.form.get("password", "")   # never strip a password

        def reject(message):
            """Re-render the confirmation with the error and its context.

            The password is deliberately absent: retyping it is the smaller
            cost, and it keeps the plain value out of the rendered HTML.
            """
            return render_template(
                "profile_delete.html",
                error=message,
                count=summary["count"],
                total=summary["total"],
            )

        if not password:
            return reject("Please enter your password to confirm.")

        # Re-authentication in front of the irreversible operation, the same
        # gate the change-password route applies. A signed-in session is not on
        # its own enough to destroy the account it belongs to — an unattended
        # browser should not be one click away from that.
        if not check_password_hash(user["password_hash"], password):
            return reject("That password is not correct.")

        # One statement, and deliberately only one. expenses.user_id is declared
        # REFERENCES users(id) ON DELETE CASCADE, and get_db() turns on the
        # foreign_keys PRAGMA per connection, so SQLite removes this account's
        # expenses as part of this DELETE. Deleting from `expenses` by hand
        # would hide the very guarantee the schema exists to provide — and would
        # also hide the day someone opens a connection without that PRAGMA, when
        # the rule is silently ignored and every row is orphaned instead.
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()
    finally:
        # `with get_db() as conn` commits but does not close; see the get_db()
        # docstring. Closing by hand is the only way to release the file.
        conn.close()

    # clear(), not session.pop("user_id"): base.html keys the nav off
    # session.user_id, but it renders session.name too, so popping one key would
    # leave the greeting behind while the account it names no longer exists.
    # Nothing in this cookie points at anything any more.
    session.clear()

    # Worth knowing in development: seed_db() returns early only while `users`
    # holds a row, so deleting the last account means the next start re-seeds
    # the demo data from scratch. That is the seeding rule working, not a
    # deletion that failed to take.
    return redirect(url_for("landing"))


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
