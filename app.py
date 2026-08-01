import math
import os
import sqlite3
from datetime import date, timedelta

from flask import Flask, abort, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from database.db import CATEGORIES, format_inr, get_db, init_db, seed_db, to_local

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


# Shown when the range in the query string cannot be used. Both leave the page
# on all-time figures: a half-applied filter would quietly report numbers for a
# window nobody asked for, which is worse than reporting nothing was applied.
RANGE_INVALID = "Please enter dates as YYYY-MM-DD."
RANGE_BACKWARDS = "The start date is after the end date."


def parse_range(args):
    """Turn ?start= / ?end= into (start, end, error).

    Each bound comes back as a `date` or as None, and None means unbounded on
    that side — so a missing pair is exactly the unfiltered page Step 4 built.

    Nothing this returns has been anywhere near SQL. The caller binds
    `.isoformat()` of these values, which means the only date strings a query
    ever sees are ones `date.fromisoformat` has already vouched for. That is
    the whole point of parsing here rather than passing `args` along: these two
    values arrive from the address bar, where anyone can type anything.
    """
    def bound(name):
        raw = args.get(name, "").strip()
        # fromisoformat is the entire validation. It accepts 'YYYY-MM-DD' and
        # raises on '2026-13-45', on 'today', and on anything carrying a quote.
        return date.fromisoformat(raw) if raw else None

    try:
        start = bound("start")
        end = bound("end")
    except ValueError:
        return None, None, RANGE_INVALID

    # Reported rather than swapped. A range typed backwards is a mistake, and
    # silently correcting it would teach the visitor that it worked.
    if start and end and start > end:
        return None, None, RANGE_BACKWARDS

    return start, end, None


def format_day(day):
    """Render a bound the way the page speaks: 1 Jul 2026.

    Deliberately not strftime('%d %b %Y'), which zero-pads to '01 Jul 2026' and
    reads like a filename. "Member since" keeps its own longer form.
    """
    return f"{day.day} {day.strftime('%b %Y')}"


def describe_range(start, end):
    """The sentence above the figures naming the window they cover."""
    if start and end:
        return f"Showing {format_day(start)} to {format_day(end)}"
    if start:
        return f"Showing everything from {format_day(start)}"
    if end:
        return f"Showing everything up to {format_day(end)}"
    return "Showing all time"


def range_presets(today=None):
    """The one-click ranges, worked out server-side and rendered as links.

    Links rather than a `?range=this-month` parameter on purpose: a preset that
    resolved to dates only inside the route would be a second way to express a
    range, and parse_range() would need to handle both. Here every preset is
    just a pair of bounds in a URL, which is what the form produces too.
    """
    today = today or date.today()
    return [
        {"label": label, "start": first.isoformat(), "end": last.isoformat()}
        for label, first, last in (
            ("This month", today.replace(day=1), today),
            # 29, not 30: the window is inclusive at both ends, so today plus
            # the 29 days behind it is 30 days of spending.
            ("Last 30 days", today - timedelta(days=29), today),
            ("This year", today.replace(month=1, day=1), today),
        )
    ]


@app.route("/profile")
@app.route("/profile/<int:requested_id>")
def profile(requested_id=None):
    # Two URLs, one page: /profile is the canonical address, and
    # /profile/<id> is the dynamic form — the first route in the app whose
    # path carries a value. `<int:...>` matches digits only, so it never
    # shadows the static /profile/edit, /profile/password or /profile/delete
    # rules below.
    #
    # The parameter is named `requested_id` rather than `user_id` on purpose.
    # It is a number a visitor typed, and the rest of this function must not
    # be able to reach for it by the name it uses for identity — every query
    # below stays bound to the session.

    # The first route that requires a signed-in user. Every logged-in feature
    # from here on repeats this shape: read the identity from the session, and
    # scope every query to it — never to anything the visitor can type.
    user_id = session.get("user_id")
    if not user_id:
        return redirect(url_for("login"))

    # A URL id is a request, not a claim. It is allowed to name the account
    # already signed in and nothing else, which leaves the id in the address
    # bar as a label for the page rather than a way to choose whose page it is.
    # Drop this check and /profile/2 becomes every other account's name, email
    # and spending — the classic insecure-direct-object-reference bug, and the
    # reason specs 04 and 05 rule out an id-driven route that trusts its input.
    #
    # 404 rather than 403: "forbidden" would confirm that account exists, so a
    # stranger could walk the ids and learn how many users there are. "Not
    # found" is the same answer for an id that is somebody else's and an id
    # that was never issued, and it tells them apart for nobody.
    if requested_id is not None and requested_id != user_id:
        abort(404)

    # Read only after both guards above. A range narrows a result set that is
    # already this account's; it is never a way to widen one, and it is never
    # looked at before the identity behind it is known.
    start, end, range_error = parse_range(request.args)

    # Assembled from string literals written in this file and nothing else, so
    # concatenating it into the queries below cannot smuggle anything in. The
    # dates travel separately as bound parameters — that separation is what
    # makes a query built this way safe, not the fact that the values parsed.
    clause = ""
    params = [user_id]
    if start:
        clause += " AND date >= ?"
        params.append(start.isoformat())
    if end:
        clause += " AND date <= ?"
        params.append(end.isoformat())
    params = tuple(params)

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

        # `clause` is empty on the unfiltered page, so both statements below
        # are byte-for-byte what Step 4 ran. expenses.date holds ISO
        # 'YYYY-MM-DD', which compares lexicographically in SQLite — that is
        # why a plain >= / <= is a correct date comparison here and no
        # strftime() is needed (see the schema note in database/db.py).
        summary = conn.execute(
            "SELECT COUNT(*) AS count, COALESCE(SUM(amount), 0) AS total"
            "  FROM expenses WHERE user_id = ?" + clause,
            params,
        ).fetchone()

        breakdown = conn.execute(
            "SELECT category, SUM(amount) AS total FROM expenses"
            "  WHERE user_id = ?" + clause +
            "  GROUP BY category ORDER BY total DESC",
            params,
        ).fetchall()

        # The same `clause` and the same `params` the two statements above use, so
        # the list and the figures can never disagree about which rows are in
        # scope — a list showing rows the tiles did not count would make the page
        # contradict itself.
        #
        # Deliberately uncapped. This list is the only route to an expense's edit
        # form, so a LIMIT would strand every older row as uneditable; the date
        # filter above is what narrows a long list. Newest first, with id breaking
        # ties, because several expenses commonly share one date.
        expense_rows = conn.execute(
            "SELECT id, amount, category, date, description FROM expenses"
            "  WHERE user_id = ?" + clause +
            "  ORDER BY date DESC, id DESC",
            params,
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

    # Dates rendered here rather than in the template, through the same helper the
    # range note uses, so one page never speaks about dates in two voices. The
    # stored ISO string is kept alongside it — the row's own edit link needs
    # nothing else, but a reader comparing the list against the filter above does.
    expenses = [
        {
            "id": row["id"],
            "amount": row["amount"],
            "category": row["category"],
            "day": format_day(date.fromisoformat(row["date"])),
            "description": row["description"],
        }
        for row in expense_rows
    ]

    # Replaces Step 4's "This month" tile. Once any window can be chosen, a
    # figure hard-wired to the calendar month contradicts the three tiles
    # beside it; "this month" survives as a preset instead. The guard matters —
    # an empty range divides by zero otherwise.
    average = summary["total"] / summary["count"] if summary["count"] else 0

    # The fields echo the parsed bound when there is one, because canonical
    # 'YYYY-MM-DD' is the only thing <input type="date"> will display. On a
    # rejected range they fall back to the raw text, so what was typed stays
    # beside the error explaining it.
    raw_start = request.args.get("start", "").strip()
    raw_end = request.args.get("end", "").strip()

    return render_template(
        "profile.html",
        user=user,
        # created_at is stored UTC; to_local() is what keeps an IST reader from
        # seeing a join date five and a half hours early.
        member_since=to_local(user["created_at"]).strftime("%d %B %Y"),
        total=summary["total"],
        count=summary["count"],
        average=average,
        categories=categories,
        expenses=expenses,
        top_category=categories[0]["name"] if categories else None,
        start=start.isoformat() if start else raw_start,
        end=end.isoformat() if end else raw_end,
        range_error=range_error,
        range_note=describe_range(start, end),
        # What separates "nothing in this window" from "nothing at all". Note
        # it is false when a range was rejected — those figures are all-time,
        # and the page must not claim otherwise.
        has_range=bool(start or end),
        presets=range_presets(),
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


@app.route("/analytics")
def analytics():
    # The same guard /profile and every account route above use: identity is
    # read from the session and nothing else. There is no query yet — the page
    # is a placeholder — but the gate goes on now rather than later, so the
    # route never spends a single commit answering to logged-out visitors.
    #
    # Redirect rather than 404: unlike /profile/<id>, this URL is the same page
    # for everyone, so there is nothing to disclose by admitting it exists. The
    # useful answer to "you are not signed in" is the sign-in form.
    if not session.get("user_id"):
        return redirect(url_for("login"))

    return render_template("analytics.html")


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
# Expenses                                                            #
# ------------------------------------------------------------------ #

# A typo guard, not a business rule: nobody is stopped from recording a large
# expense, but an amount this size is far more likely to be a slipped finger on
# the keyboard than a real one, and a single stray row of that magnitude makes
# every total and every bar on /profile useless.
AMOUNT_MAX = 10_000_000

# Long enough for a real note, short enough that the column stays a label rather
# than becoming somewhere to paste an essay.
DESCRIPTION_MAX = 200

# Both name their own limit, so the message cannot drift out of step with the
# constant it describes. The rupee figure goes through format_inr for the same
# reason every amount in the UI does — Indian digit grouping in exactly one
# place, never a "₹" built by hand here.
AMOUNT_TOO_LARGE = f"Please enter an amount no greater than {format_inr(AMOUNT_MAX)}."
DESCRIPTION_TOO_LONG = (
    f"Please keep the description under {DESCRIPTION_MAX} characters."
)

# Named because two separate branches below reach it — a value float() cannot read
# at all, and one it reads as an infinity — and they must say the same thing.
AMOUNT_NOT_A_NUMBER = "Please enter the amount as a number, like 250 or 99.50."


def parse_expense_form(form):
    """Validate one submitted expense, whether it is being added or edited.

    Returns `(fields, values, error)`:

        fields — exactly what the visitor typed, ready to echo back into the form
        values — the cleaned amount, category, date and description ready to bind,
                 or None when there is an error
        error  — None, or the one message naming what to fix

    Both expense routes call this. That is the point of it being a function: an
    edit form that validated more permissively than the add form would be a way to
    write a value the add form refuses, and a rule that lives in one place cannot
    drift between the two.

    `fields` is returned on the success path too, and it is always populated —
    everything the visitor got right stays on the page, so fixing one field never
    means retyping the other three. Only the date is ever normalised: it holds the
    canonical 'YYYY-MM-DD' once it has parsed, because <input type="date"> will not
    display anything else, and the raw string before then so that what was typed
    stays beside the error explaining it.
    """
    amount_raw = form.get("amount", "").strip()
    category = form.get("category", "").strip()
    date_raw = form.get("date", "").strip()
    description = form.get("description", "").strip()

    fields = {
        "amount": amount_raw,
        "category": category,
        "date": date_raw,
        "description": description,
    }

    def fail(message):
        return fields, None, message

    # The templates' `required`, `min` and `step` attributes and the <select>'s
    # fixed list of options are conveniences for the browser, not controls. Every
    # one of them is checked again below, because a POST never has to come from the
    # form that was rendered.
    #
    # description is absent from this check on purpose — it is the one optional
    # field.
    if not amount_raw or not category or not date_raw:
        return fail("Please fill in every field.")

    try:
        amount = float(amount_raw)
    except ValueError:
        return fail(AMOUNT_NOT_A_NUMBER)

    # float() accepts 'inf', 'infinity' and 'nan', and turns '1e400' into inf
    # without complaint. Any of them would make SUM(amount) on /profile inf or nan
    # for the life of the account — a single row that permanently breaks every
    # figure on the page. This is the check that stops it.
    if not math.isfinite(amount):
        return fail(AMOUNT_NOT_A_NUMBER)
    if amount <= 0:
        return fail("Please enter an amount greater than zero.")
    if amount > AMOUNT_MAX:
        return fail(AMOUNT_TOO_LARGE)

    # Rounded before it is stored, not on the way out: amount is REAL, and a column
    # full of unrounded input makes the totals drift by fractions of a paisa that
    # eventually show up in a figure someone is reading.
    amount = round(amount, 2)

    # The whole point of the field. A rendered <select> offers seven values; a POST
    # can name anything at all, and 'Bribes' or "Food'; DROP TABLE" must be refused
    # rather than stored. CATEGORIES is the single source both this check and the
    # dropdown read from.
    if category not in CATEGORIES:
        return fail("Please choose a category from the list.")

    # Parsed inline rather than through parse_range(): that helper answers a
    # different question — two optional bounds where blank means unbounded — and
    # bending it to serve this field would make a missing date silently valid.
    # fromisoformat is the entire validation, and it accepts only 'YYYY-MM-DD',
    # which is exactly what the column stores.
    try:
        spent_on = date.fromisoformat(date_raw)
    except ValueError:
        return fail("Please enter the date as YYYY-MM-DD.")

    # It parsed, so the field can hold it. Every rejection from here on echoes the
    # canonical form; the ones above echo the raw string, because a date the field
    # cannot display is better shown as typed than silently blanked.
    fields["date"] = spent_on.isoformat()

    # You cannot have spent money tomorrow. Everything downstream assumes it too:
    # seed_db() never dates a row ahead, and Step 6's presets all end at today, so a
    # future row would sit outside every preset range while still counting towards
    # the all-time total.
    if spent_on > date.today():
        return fail("That date is in the future.")

    # Rejected rather than truncated. Silently storing the first 200 characters
    # would tell the visitor their note was saved when part of it was thrown away.
    if len(description) > DESCRIPTION_MAX:
        return fail(DESCRIPTION_TOO_LONG)

    values = {
        "amount": amount,
        "category": category,
        "date": spent_on.isoformat(),
        # `or None` is what keeps the nullable column honest: a blank note is the
        # absence of a note, not the empty string.
        "description": description or None,
    }
    return fields, values, None


@app.route("/expenses/add", methods=["GET", "POST"])
def add_expense():
    # The first route that writes a row a user composed. Everything the form
    # sends is a suggestion; the only value here that is not is the account it
    # belongs to, which comes from the session below and from nowhere else.

    # Same guard the account routes use, and it runs first: `request.form` is
    # never read before the visitor's identity is known, because anything can
    # POST straight at this URL without ever loading the form.
    user_id = session.get("user_id")
    if not user_id:
        return redirect(url_for("login"))

    conn = get_db()
    try:
        # expenses.user_id is declared NOT NULL REFERENCES users(id) and get_db()
        # turns the foreign_keys PRAGMA on, so inserting against an id that no
        # longer exists raises IntegrityError. Checking here turns that 500 into
        # the fresh login the visitor actually needs — the same treatment
        # /profile and the account routes give a cookie left over from a
        # database that has since been rebuilt.
        if conn.execute(
            "SELECT id FROM users WHERE id = ?", (user_id,)
        ).fetchone() is None:
            session.clear()
            return redirect(url_for("login"))

        if request.method == "GET":
            # Today is the overwhelmingly common answer and the only field worth
            # pre-filling: an amount would be a guess, and a category picked on
            # the visitor's behalf is a category they did not choose.
            return render_template(
                "expense_add.html",
                categories=CATEGORIES,
                description_max=DESCRIPTION_MAX,
                date=date.today().isoformat(),
            )

        # Every rule lives in parse_expense_form() so the edit route in Step 8
        # cannot drift away from it. Only the rendering below is this route's own.
        fields, values, error = parse_expense_form(request.form)

        if error:
            # Re-render the form with the error and the submitted values, so
            # fixing one field never means retyping the other three.
            return render_template(
                "expense_add.html",
                error=error,
                categories=CATEGORIES,
                description_max=DESCRIPTION_MAX,
                **fields,
            )

        # Every value bound as a parameter, the same shape seed_db() inserts.
        # user_id is the session's, never the form's — a form that could name its
        # owner is how one account writes rows into another's ledger.
        #
        # created_at is deliberately absent from the column list so the schema's
        # datetime('now') default fires and the timestamp stays UTC. Passing
        # date.today() would quietly store local time in a column every reader
        # converts *from* UTC.
        conn.execute(
            "INSERT INTO expenses (user_id, amount, category, date, description)"
            " VALUES (?, ?, ?, ?, ?)",
            (
                user_id,
                values["amount"],
                values["category"],
                values["date"],
                values["description"],
            ),
        )
        conn.commit()
    finally:
        # `with get_db() as conn` commits but does not close; see the get_db()
        # docstring. Closing by hand is the only way to release the file.
        conn.close()

    # A redirect, not a render. A POST that answers with HTML leaves the insert
    # sitting in the browser's history, where a refresh adds the expense a second
    # time without anyone clicking anything. ?added=1 is the same notice pattern
    # Step 5 established for ?updated=1 and ?password=1.
    return redirect(url_for("profile", added=1))


@app.route("/expenses/<int:id>/edit", methods=["GET", "POST"])
def edit_expense(id):
    # The first route where a value from the URL names a database row. Every route
    # before this one scoped its queries to the session and nothing else; `id` is a
    # number a visitor can type, and the only thing between it and somebody else's
    # expense is the `AND user_id = ?` on both statements below.
    #
    # /profile/<int:requested_id> rehearsed the reasoning (see the comment there),
    # but it could compare the id against the session directly. Here the id names a
    # row in another table, so ownership has to be established by the query itself.

    # Same guard the account routes use, and it runs first: `request.form` is never
    # read before the visitor's identity is known, and neither is the row. A logged
    # out request must get the login form and never a 404 — answering "not found"
    # here would tell a stranger which ids exist without their signing in at all.
    user_id = session.get("user_id")
    if not user_id:
        return redirect(url_for("login"))

    conn = get_db()
    try:
        # A cookie left over from a database that has since been rebuilt. The
        # ownership-scoped SELECT below would return nothing for a deleted account
        # and 404 — correct, but useless. Checking here sends the visitor to the
        # fresh login they actually need, as add_expense() does.
        if conn.execute(
            "SELECT id FROM users WHERE id = ?", (user_id,)
        ).fetchone() is None:
            session.clear()
            return redirect(url_for("login"))

        # Ownership enforced in the WHERE clause, not in Python afterwards. Fetching
        # by id alone and comparing row["user_id"] would work, but it reads the row
        # before the reader is entitled to it and puts the check one careless edit
        # away from being dropped.
        expense = conn.execute(
            "SELECT id, amount, category, date, description FROM expenses"
            "  WHERE id = ? AND user_id = ?",
            (id, user_id),
        ).fetchone()

        # 404 rather than 403, and the same 404 for an id that belongs to somebody
        # else and an id that was never issued. "Forbidden" would confirm the row
        # exists, so a stranger could walk the ids and learn how many expenses the
        # app holds. "Not found" tells the two apart for nobody.
        if expense is None:
            abort(404)

        if request.method == "GET":
            # Prefilled from the row, so "save" without touching a field is a no-op
            # rather than a way to blank the expense out.
            return render_template(
                "expense_edit.html",
                categories=CATEGORIES,
                description_max=DESCRIPTION_MAX,
                id=expense["id"],
                # Trailing zeros trimmed so a whole-rupee row reads "3450" rather
                # than "3450.0". The column is REAL, and str() of a float always
                # carries the point; formatting to 2dp first keeps the paise on the
                # rows that have them, and avoids the scientific notation "%g"
                # would produce near the ceiling.
                amount=f"{expense['amount']:.2f}".rstrip("0").rstrip("."),
                category=expense["category"],
                date=expense["date"],
                description=expense["description"] or "",
            )

        # The same rules the add form applies, from the same function. An edit that
        # validated more permissively would be a way to write a value /expenses/add
        # refuses.
        fields, values, error = parse_expense_form(request.form)

        if error:
            # This route's own rendering, unlike its validation: the edit form needs
            # `id` in its context so its action attribute can be rebuilt.
            return render_template(
                "expense_edit.html",
                error=error,
                categories=CATEGORIES,
                description_max=DESCRIPTION_MAX,
                id=expense["id"],
                **fields,
            )

        # Scoped to the session's id a second time. The row was already proved to be
        # this account's by the SELECT above, so the repetition is belt-and-braces —
        # but it is the statement that actually writes, and it should not depend on
        # a check made several lines earlier to be safe on its own.
        #
        # user_id is deliberately absent from the SET list: an edit cannot move a row
        # between accounts, and a route that could would be a way to plant rows in
        # somebody else's ledger. created_at is absent for a different reason — it
        # records when the expense was entered, not when it was last touched.
        conn.execute(
            "UPDATE expenses SET amount = ?, category = ?, date = ?, description = ?"
            "  WHERE id = ? AND user_id = ?",
            (
                values["amount"],
                values["category"],
                values["date"],
                values["description"],
                id,
                user_id,
            ),
        )
        conn.commit()
    finally:
        # `with get_db() as conn` commits but does not close; see the get_db()
        # docstring. Closing by hand is the only way to release the file.
        conn.close()

    # A redirect, not a render, for the reason add_expense() gives: a POST that
    # answers with HTML leaves the update sitting in the browser's history. Note
    # that a submit which changed nothing still lands here — re-saving an expense
    # unchanged is not a mistake worth an error, unlike a password "change" that
    # changes nothing.
    return redirect(url_for("profile", edited=1))


@app.route("/expenses/<int:id>/delete", methods=["GET", "POST"])
def delete_expense(id):
    # `methods` is spelled out, and that is the whole point of this route. Until
    # now the rule was `@app.route("/expenses/<int:id>/delete")` — GET-only by
    # omission — and a destructive GET fires on a link prefetch, on a crawler, or
    # on a browser restoring tabs, with nobody having clicked anything. The
    # confirmation below renders on GET and the row is destroyed only on POST,
    # the same split /profile/delete uses (see the comment at its GET branch).
    #
    # No re-authentication here, and the asymmetry with /profile/delete is
    # deliberate. That route asks for the password because it destroys an account
    # and every expense in it. This destroys one row whose every field is on the
    # screen immediately before it goes, so re-entering it costs a single form.
    # The confirmation screen is the guard on this route.

    # Same guard the account routes use, and it runs first: neither the row nor
    # `request.form` is looked at before the visitor's identity is known. A logged
    # out request must get the login form and never a 404 — answering "not found"
    # here would tell a stranger which ids exist without their signing in at all.
    user_id = session.get("user_id")
    if not user_id:
        return redirect(url_for("login"))

    conn = get_db()
    try:
        # A cookie left over from a database that has since been rebuilt. The
        # ownership-scoped SELECT below would return nothing for a deleted account
        # and 404 — correct, but useless. Checking here sends the visitor to the
        # fresh login they actually need, as add_expense() and edit_expense() do.
        if conn.execute(
            "SELECT id FROM users WHERE id = ?", (user_id,)
        ).fetchone() is None:
            session.clear()
            return redirect(url_for("login"))

        # Ownership enforced in the WHERE clause, exactly as edit_expense() does
        # it. Only the four columns the confirmation screen names are read — this
        # route displays the row, it never writes one back.
        expense = conn.execute(
            "SELECT amount, category, date, description FROM expenses"
            "  WHERE id = ? AND user_id = ?",
            (id, user_id),
        ).fetchone()

        # 404 rather than 403, and the same 404 for an id that belongs to somebody
        # else and an id that was never issued — the reasoning /profile and the
        # edit route both carry. It is also the answer a second submit of an
        # already-deleted row gets: the SELECT finds nothing, and this abort runs
        # before anything can touch the row that is no longer there.
        if expense is None:
            abort(404)

        if request.method == "GET":
            # Renders the confirmation and deletes nothing. Every field goes to the
            # template because naming the row in full is what makes this reversible
            # by hand — the screen holds everything needed to type the expense back
            # in. The date is formatted here, through the same helper /profile uses,
            # so one app never speaks about dates in two voices.
            return render_template(
                "expense_delete.html",
                id=id,
                amount=expense["amount"],
                category=expense["category"],
                day=format_day(date.fromisoformat(expense["date"])),
                description=expense["description"],
            )

        # Scoped to the session's id a second time. The row was already proved to be
        # this account's by the SELECT above, so the repetition is belt-and-braces —
        # but it is the statement that actually destroys, and it should not depend on
        # a check made several lines earlier to be safe on its own.
        #
        # One row, named by its primary key. Never `DELETE FROM expenses WHERE
        # user_id = ?` without an id, which would empty the whole ledger, and never
        # a second statement "cleaning up" after it: expenses is a leaf table, and
        # the ON DELETE CASCADE in the schema points from here *at* users, not away.
        conn.execute(
            "DELETE FROM expenses WHERE id = ? AND user_id = ?", (id, user_id)
        )
        conn.commit()
    finally:
        # `with get_db() as conn` commits but does not close; see the get_db()
        # docstring. Closing by hand is the only way to release the file.
        conn.close()

    # A redirect, not a render, for the reason add_expense() gives: a POST that
    # answers with HTML leaves the delete sitting in the browser's history, where a
    # refresh replays it. ?deleted=1 is the same notice pattern as ?added=1 and
    # ?edited=1. No range parameters — those two do not carry them either.
    return redirect(url_for("profile", deleted=1))


if __name__ == "__main__":
    app.run(debug=True, port=5001)
