"""Tests for the Step 1 database layer."""

import importlib
import os
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from database import db


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """Point the data layer at a throwaway database file.

    get_db() reads the module-level DB_PATH at call time, so patching it here
    keeps every test off the real spendly.db.
    """
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    db.init_db()
    return db


def table_names(conn):
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    return {row["name"] for row in rows}


def add_user(conn, email="demo@spendly.com"):
    cursor = conn.execute(
        "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
        ("Demo User", email, "not-a-real-hash"),
    )
    return cursor.lastrowid


# ------------------------------------------------------------------ #
# init_db                                                             #
# ------------------------------------------------------------------ #

def test_init_db_creates_tables(temp_db):
    conn = temp_db.get_db()
    try:
        assert {"users", "expenses"} <= table_names(conn)
    finally:
        conn.close()


def test_init_db_is_idempotent(temp_db):
    """CREATE TABLE IF NOT EXISTS means a second run must not raise or wipe data."""
    conn = temp_db.get_db()
    try:
        add_user(conn)
        conn.commit()
    finally:
        conn.close()

    temp_db.init_db()

    conn = temp_db.get_db()
    try:
        assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1
    finally:
        conn.close()


# ------------------------------------------------------------------ #
# get_db                                                              #
# ------------------------------------------------------------------ #

def test_rows_support_column_names(temp_db):
    conn = temp_db.get_db()
    try:
        add_user(conn)
        row = conn.execute("SELECT * FROM users").fetchone()
        assert row["email"] == "demo@spendly.com"   # row_factory is set
        assert row["name"] == "Demo User"
    finally:
        conn.close()


def test_foreign_keys_pragma_is_on(temp_db):
    conn = temp_db.get_db()
    try:
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    finally:
        conn.close()


def test_db_file_is_named_spendly():
    """Deliberately skips the temp_db fixture to assert the configured path."""
    assert db.DB_PATH.name in ("spendly.db", "spendly-test.db")


def test_spendly_db_env_var_redirects_the_path():
    """conftest.py relies on this to keep the test run off the dev database."""
    assert db.DB_PATH == Path(os.environ["SPENDLY_DB"])
    assert db.DB_PATH.name != "spendly.db"


def test_importing_app_does_not_touch_the_development_database():
    """app.py seeds at import time; that must land in the redirected file."""
    dev_db = Path(__file__).resolve().parent.parent / "spendly.db"
    before = dev_db.stat().st_mtime if dev_db.exists() else None

    importlib.import_module("app")

    after = dev_db.stat().st_mtime if dev_db.exists() else None
    assert before == after, "importing app wrote to the real spendly.db"


# ------------------------------------------------------------------ #
# Constraints                                                         #
# ------------------------------------------------------------------ #

def test_expense_requires_an_existing_user(temp_db):
    """Proves the foreign key is actually enforced, not just declared."""
    conn = temp_db.get_db()
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO expenses (user_id, amount, category, date)"
                " VALUES (?, ?, ?, ?)",
                (999, 250.0, "Food", "2026-07-22"),
            )
    finally:
        conn.close()


def test_deleting_a_user_cascades_to_expenses(temp_db):
    conn = temp_db.get_db()
    try:
        user_id = add_user(conn)
        conn.execute(
            "INSERT INTO expenses (user_id, amount, category, date)"
            " VALUES (?, ?, ?, ?)",
            (user_id, 250.0, "Food", "2026-07-22"),
        )
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()

        assert conn.execute("SELECT COUNT(*) FROM expenses").fetchone()[0] == 0
    finally:
        conn.close()


def test_duplicate_email_is_rejected(temp_db):
    conn = temp_db.get_db()
    try:
        add_user(conn)
        with pytest.raises(sqlite3.IntegrityError):
            add_user(conn)
    finally:
        conn.close()


# ------------------------------------------------------------------ #
# seed_db                                                             #
# ------------------------------------------------------------------ #

def test_seed_inserts_the_demo_data(temp_db):
    temp_db.seed_db()

    conn = temp_db.get_db()
    try:
        user = conn.execute("SELECT * FROM users").fetchone()
        assert user["email"] == "demo@spendly.com"

        count = conn.execute("SELECT COUNT(*) FROM expenses").fetchone()[0]
        assert count == 8

        total = conn.execute("SELECT SUM(amount) FROM expenses").fetchone()[0]
        assert total == pytest.approx(18240.0)   # matches the landing page figure
    finally:
        conn.close()


def test_seed_covers_every_category(temp_db):
    temp_db.seed_db()

    conn = temp_db.get_db()
    try:
        rows = conn.execute("SELECT DISTINCT category FROM expenses")
        seeded = {row["category"] for row in rows}
        assert seeded == set(temp_db.CATEGORIES)
    finally:
        conn.close()


def test_seed_is_idempotent(temp_db):
    temp_db.seed_db()
    temp_db.seed_db()

    conn = temp_db.get_db()
    try:
        assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM expenses").fetchone()[0] == 8
    finally:
        conn.close()


def test_seeded_password_is_hashed(temp_db):
    temp_db.seed_db()

    conn = temp_db.get_db()
    try:
        row = conn.execute("SELECT password_hash FROM users").fetchone()
        assert row["password_hash"] != temp_db.DEMO_USER["password"]
        assert temp_db.DEMO_USER["password"] not in row["password_hash"]
    finally:
        conn.close()


def test_seeded_dates_are_iso_and_not_in_the_future(temp_db):
    temp_db.seed_db()

    conn = temp_db.get_db()
    try:
        rows = conn.execute("SELECT date FROM expenses ORDER BY date")
        dates = [row["date"] for row in rows]
    finally:
        conn.close()

    for value in dates:
        date.fromisoformat(value)          # raises if not YYYY-MM-DD
    assert dates[-1] <= date.today().isoformat()


def test_seeded_dates_are_distinct(temp_db):
    """Two expenses sharing a date makes the sample data look bunched."""
    temp_db.seed_db()

    conn = temp_db.get_db()
    try:
        rows = conn.execute("SELECT date FROM expenses")
        dates = [row["date"] for row in rows]
    finally:
        conn.close()

    assert len(set(dates)) == len(dates)


def test_created_at_is_stored_as_utc(temp_db):
    """Storing local time would silently mix zones across machines."""
    conn = temp_db.get_db()
    try:
        add_user(conn)
        conn.commit()
        stamp = conn.execute("SELECT created_at FROM users").fetchone()["created_at"]
    finally:
        conn.close()

    written = datetime.fromisoformat(stamp).replace(tzinfo=timezone.utc)
    assert abs((datetime.now(timezone.utc) - written).total_seconds()) < 120


def test_to_local_converts_a_stored_timestamp(temp_db):
    conn = temp_db.get_db()
    try:
        add_user(conn)
        conn.commit()
        stamp = conn.execute("SELECT created_at FROM users").fetchone()["created_at"]
    finally:
        conn.close()

    local = temp_db.to_local(stamp)
    assert local.tzinfo is not None                      # aware, not naive
    assert abs((datetime.now().astimezone() - local).total_seconds()) < 120


def test_to_local_applies_the_utc_offset():
    """A fixed UTC instant must come back as the same instant, not the same clock face."""
    local = db.to_local("2026-07-22 06:40:00")
    assert local.utcoffset() is not None
    assert local.replace(tzinfo=None) == (
        datetime(2026, 7, 22, 6, 40) + local.utcoffset()
    )


# ------------------------------------------------------------------ #
# spread_dates                                                        #
# ------------------------------------------------------------------ #

@pytest.mark.parametrize("today_day", range(1, 29))
def test_spread_dates_never_goes_past_today(today_day):
    today = date(2026, 7, today_day)
    dates = db.spread_dates(8, today=today)

    assert len(dates) == 8
    assert all(value <= today.isoformat() for value in dates)
    assert dates == sorted(dates)


@pytest.mark.parametrize("today_day", range(8, 29))
def test_spread_dates_are_distinct_once_the_month_is_long_enough(today_day):
    """With 8 expenses, any day >= 8 has room for one date each."""
    dates = db.spread_dates(8, today=date(2026, 7, today_day))
    assert len(set(dates)) == 8


def test_spread_dates_ends_on_today():
    dates = db.spread_dates(8, today=date(2026, 7, 22))
    assert dates[-1] == "2026-07-22"
    assert dates[0] == "2026-07-01"


# ------------------------------------------------------------------ #
# format_inr                                                          #
# ------------------------------------------------------------------ #

@pytest.mark.parametrize(
    "amount, expected",
    [
        (0, "₹0"),
        (250, "₹250"),
        (18240, "₹18,240"),
        (118240, "₹1,18,240"),
        (10000000, "₹1,00,00,000"),
        (-1180.4, "-₹1,180"),
    ],
)
def test_format_inr(amount, expected):
    assert db.format_inr(amount) == expected
