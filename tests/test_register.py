"""Tests for the Step 2 registration route."""

import pytest

from app import app
from database import db


@pytest.fixture
def client(tmp_path, monkeypatch):
    """A test client whose writes land in a throwaway database.

    app.py binds get_db by reference at import time, but get_db reads the
    module-level DB_PATH when it is *called*, so patching the attribute here
    redirects the route's writes too — the same trick test_db.py uses. Each
    test gets its own file, which is why they can all reuse one email address
    without colliding.
    """
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    db.init_db()
    app.config["TESTING"] = True
    return app.test_client()


VALID = {
    "name": "Nitish Kumar",
    "email": "nitish@example.com",
    "password": "rupees123",
}


def register(client, **overrides):
    """POST the registration form, overriding individual fields by keyword."""
    return client.post("/register", data={**VALID, **overrides})


def all_users():
    conn = db.get_db()
    try:
        return conn.execute("SELECT * FROM users").fetchall()
    finally:
        conn.close()


# ------------------------------------------------------------------ #
# The happy path                                                      #
# ------------------------------------------------------------------ #

def test_get_register_still_renders(client):
    response = client.get("/register")
    assert response.status_code == 200
    assert b"Create your account" in response.data


def test_valid_registration_redirects_to_login(client):
    response = register(client)
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]
    assert "registered=1" in response.headers["Location"]


def test_valid_registration_stores_the_user(client):
    register(client)

    rows = all_users()
    assert len(rows) == 1
    assert rows[0]["name"] == "Nitish Kumar"
    assert rows[0]["email"] == "nitish@example.com"


def test_login_page_confirms_the_new_account(client):
    response = register(client)
    landed = client.get(response.headers["Location"])
    assert b"Account created" in landed.data


def test_password_is_hashed_never_stored(client):
    register(client)

    stored = all_users()[0]["password_hash"]
    assert stored != VALID["password"]
    assert VALID["password"] not in stored
    assert stored.split(":")[0] in ("scrypt", "pbkdf2")


def test_email_is_stored_lowercased(client):
    register(client, email="Nitish@Example.COM")
    assert all_users()[0]["email"] == "nitish@example.com"


def test_name_is_stripped(client):
    register(client, name="  Nitish Kumar  ")
    assert all_users()[0]["name"] == "Nitish Kumar"


def test_password_is_not_stripped(client):
    """Trimming a password silently changes what the user typed."""
    register(client, password="  spaces  ")
    assert len(all_users()) == 1        # 10 characters, so it passed the length rule


# ------------------------------------------------------------------ #
# Duplicate addresses                                                 #
# ------------------------------------------------------------------ #

def test_duplicate_email_is_rejected(client):
    register(client)
    response = register(client, name="Someone Else")

    assert response.status_code == 200
    assert b"already exists" in response.data
    assert len(all_users()) == 1


def test_duplicate_email_ignores_case(client):
    """Without normalisation SQLite's UNIQUE would let this through."""
    register(client)
    response = register(client, email="NITISH@EXAMPLE.COM")

    assert b"already exists" in response.data
    assert len(all_users()) == 1


def test_seeded_demo_account_cannot_be_re_registered(client):
    db.seed_db()
    response = register(client, email="DEMO@SPENDLY.COM")

    assert b"already exists" in response.data
    assert len(all_users()) == 1


# ------------------------------------------------------------------ #
# Validation                                                          #
# ------------------------------------------------------------------ #

@pytest.mark.parametrize("field", ["name", "email", "password"])
def test_blank_fields_are_rejected(client, field):
    """The template's `required` is a browser convenience, not a control."""
    response = register(client, **{field: "   " if field != "password" else "  "})

    assert response.status_code == 200
    assert not all_users()


@pytest.mark.parametrize(
    "email",
    ["notanemail", "@example.com", "nitish@", "nitish@com", "nitish@.com"],
)
def test_malformed_emails_are_rejected(client, email):
    response = register(client, email=email)

    assert b"valid email" in response.data
    assert not all_users()


def test_short_password_is_rejected(client):
    response = register(client, password="7chars!")     # one short

    assert b"at least 8 characters" in response.data
    assert not all_users()


def test_eight_character_password_is_accepted(client):
    """The boundary the placeholder text promises."""
    response = register(client, password="8chars!!")

    assert response.status_code == 302
    assert len(all_users()) == 1


# ------------------------------------------------------------------ #
# What a rejected form gives back                                     #
# ------------------------------------------------------------------ #

def test_rejected_submit_keeps_name_and_email(client):
    response = register(client, password="short")

    assert b"Nitish Kumar" in response.data
    assert b"nitish@example.com" in response.data


def test_rejected_submit_never_echoes_the_password(client):
    response = register(client, password="short")
    assert b"short" not in response.data
