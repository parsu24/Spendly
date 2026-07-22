"""SQLite data layer — Step 1: Database Setup.

Three functions make up the contract every later step builds on:

    get_db()   — returns a SQLite connection with row_factory and foreign keys enabled
    init_db()  — creates all tables using CREATE TABLE IF NOT EXISTS
    seed_db()  — inserts sample data for development

app.py calls init_db() and seed_db() on startup, so the database exists
before the first request. You can also rebuild it directly:

    python -m database.db

No ORM, no string-formatted SQL — every query below is parameterized.
"""

import sqlite3
from datetime import date
from pathlib import Path

from werkzeug.security import generate_password_hash

# Resolved from this file's location, not the current working directory, so
# the database always lands in the project root next to app.py no matter
# where you run python from. The file is gitignored.
DB_PATH = Path(__file__).resolve().parent.parent / "spendly.db"

# The only category values the app uses. Later steps populate their dropdowns
# from this list, so keep the two in sync.
CATEGORIES = [
    "Food",
    "Transport",
    "Bills",
    "Health",
    "Entertainment",
    "Shopping",
    "Other",
]


# ------------------------------------------------------------------ #
# Schema                                                              #
# ------------------------------------------------------------------ #

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    email         TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at    TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS expenses (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    amount      REAL    NOT NULL,
    category    TEXT    NOT NULL,
    date        TEXT    NOT NULL,
    description TEXT,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);
"""

# Schema notes worth knowing before Step 2:
#
#   users.email is UNIQUE      — this is what lets registration detect that an
#                                address is already taken, instead of silently
#                                creating a duplicate account.
#   ON DELETE CASCADE          — deleting a user removes their expenses too, but
#                                only because get_db() turns on the foreign_keys
#                                PRAGMA. Without it SQLite ignores the rule.
#   expenses.date is TEXT      — ISO 'YYYY-MM-DD' strings sort and compare
#                                correctly in SQLite, so BETWEEN works for the
#                                date-range filtering the landing page promises.
#   amount is REAL             — rupees as a float, not paise as an integer.
#   created_at uses 'localtime'— datetime('now') alone returns UTC, which would
#                                show an IST user a timestamp five and a half
#                                hours behind the clock on their wall.
#
# Changing this block does not alter a database that already exists — the
# CREATE statements are IF NOT EXISTS. Delete spendly.db and restart the app
# to pick up a schema change.


# ------------------------------------------------------------------ #
# Connection                                                          #
# ------------------------------------------------------------------ #

def get_db():
    """Open a connection to the Spendly database.

    Both settings below are per-connection, which is why they belong here
    rather than in init_db() — a connection that skips them silently loses
    dict-style row access and foreign key enforcement.

    The caller owns the connection and is responsible for closing it. Note
    that `with get_db() as conn` commits the transaction but does *not*
    close the connection; use try/finally or conn.close() when you are done.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row            # rows act like dicts: row["email"]
    conn.execute("PRAGMA foreign_keys = ON")  # off by default in SQLite
    return conn


# ------------------------------------------------------------------ #
# Setup                                                               #
# ------------------------------------------------------------------ #

def init_db():
    """Create both tables. Safe to call multiple times."""
    conn = get_db()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


# One demo account. The password is hashed even though this is throwaway
# development data — seed code is the code students copy from most.
DEMO_USER = {
    "name": "Demo User",
    "email": "demo@spendly.com",
    "password": "demo123",
}

# Eight sample expenses covering every category in CATEGORIES. Amounts are in
# rupees and total ₹18,240, so the seeded data lines up with the "This month
# ₹18,240" figure on the landing page. Listed oldest first — seed_db() assigns
# the dates.
DEMO_EXPENSES = [
    # (amount, category, description)
    (3450.0, "Food",          "Monthly groceries"),
    (2150.0, "Bills",         "Electricity bill"),
    (2400.0, "Transport",     "Metro card and cab rides"),
    (1503.0, "Health",        "Pharmacy — refill"),
    ( 899.0, "Entertainment", "Movie night"),
    (3299.0, "Shopping",      "Running shoes"),
    (3180.0, "Food",          "Dinner with friends"),
    (1359.0, "Other",         "Household odds and ends"),
]


def spread_dates(count, today=None):
    """Return `count` dates spread across the days of the current month so far.

    Seed data should look like a month of real activity, which means one date
    per expense and nothing dated in the future. Spacing the days evenly from
    the 1st up to today gives distinct dates whenever the month is at least
    `count` days old; earlier than that the month simply does not have enough
    days to go around and some will repeat.
    """
    today = today or date.today()

    if today.day >= count > 1:
        # Integer arithmetic keeps the steps evenly sized and strictly
        # increasing, so no two expenses can land on the same day.
        days = [1 + (i * (today.day - 1)) // (count - 1) for i in range(count)]
    else:
        days = [min(i + 1, today.day) for i in range(count)]

    return [today.replace(day=day).isoformat() for day in days]


def seed_db():
    """Insert sample development data.

    Idempotent: if the users table already holds any row the function returns
    without touching the database, so repeated runs never duplicate records.
    """
    conn = get_db()
    try:
        if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] > 0:
            return  # already seeded

        cursor = conn.execute(
            "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
            (
                DEMO_USER["name"],
                DEMO_USER["email"],
                generate_password_hash(DEMO_USER["password"]),
            ),
        )
        user_id = cursor.lastrowid

        dates = spread_dates(len(DEMO_EXPENSES))
        rows = [
            (user_id, amount, category, day, description)
            for (amount, category, description), day in zip(DEMO_EXPENSES, dates)
        ]
        conn.executemany(
            "INSERT INTO expenses (user_id, amount, category, date, description)"
            " VALUES (?, ?, ?, ?, ?)",
            rows,
        )
        conn.commit()

        total = sum(row[1] for row in rows)
        print(
            f"Seeded {DEMO_USER['email']} with {len(rows)} expenses "
            f"totalling {format_inr(total)}."
        )
    finally:
        conn.close()


# ------------------------------------------------------------------ #
# Helpers                                                             #
# ------------------------------------------------------------------ #

def format_inr(amount):
    """Format a rupee amount with Indian digit grouping: 118240 -> '₹1,18,240'.

    Indian grouping separates the last three digits and then every two digits
    after that, which is why str.format's comma cannot produce it.
    """
    whole = int(round(amount))
    sign = "-" if whole < 0 else ""
    digits = str(abs(whole))

    if len(digits) > 3:
        last_three, rest = digits[-3:], digits[:-3]
        groups = []
        while len(rest) > 2:          # walk the leading digits backwards in pairs
            groups.insert(0, rest[-2:])
            rest = rest[:-2]
        if rest:
            groups.insert(0, rest)
        digits = ",".join(groups + [last_three])

    return f"{sign}₹{digits}"


if __name__ == "__main__":
    init_db()
    print(f"Database ready at {DB_PATH}")
    seed_db()
