"""Tests for the Step 3 login and logout routes."""

import pytest

from app import app
from database import db


@pytest.fixture
def client(tmp_path, monkeypatch):
    """A test client whose database is a throwaway file with the demo account.

    app.py binds get_db by reference at import time, but get_db reads the
    module-level DB_PATH when it is *called*, so patching the attribute here
    redirects the route's reads too — the same trick test_register.py uses.
    seed_db() gives every test the demo@spendly.com / demo123 account to sign
    in against.
    """
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    db.init_db()
    db.seed_db()
    app.config["TESTING"] = True
    return app.test_client()


DEMO_EMAIL = "demo@spendly.com"
DEMO_PASSWORD = "demo123"

GENERIC_ERROR = b"Incorrect email or password."


def login(client, email=DEMO_EMAIL, password=DEMO_PASSWORD):
    """POST the login form."""
    return client.post("/login", data={"email": email, "password": password})


# ------------------------------------------------------------------ #
# The happy path                                                      #
# ------------------------------------------------------------------ #

def test_get_login_still_renders(client):
    response = client.get("/login")
    assert response.status_code == 200
    assert b"Welcome back" in response.data


def test_valid_login_redirects_to_landing(client):
    response = login(client)
    assert response.status_code == 302
    assert response.headers["Location"] in ("/", "http://localhost/")


def test_valid_login_sets_the_session(client):
    login(client)
    with client.session_transaction() as sess:
        assert sess["user_id"] == 1
        assert sess["name"] == "Demo User"


def test_logged_in_nav_greets_the_user(client):
    login(client)
    landed = client.get("/")
    assert b"Demo User" in landed.data
    assert b"Log out" in landed.data


def test_login_email_is_case_insensitive(client):
    """An account stored lowercase still signs in from a shouted address."""
    response = login(client, email="DEMO@SPENDLY.COM")
    assert response.status_code == 302
    with client.session_transaction() as sess:
        assert sess["user_id"] == 1


# ------------------------------------------------------------------ #
# Rejected credentials                                                #
# ------------------------------------------------------------------ #

def test_wrong_password_is_rejected(client):
    response = login(client, password="not-the-password")
    assert response.status_code == 200
    assert GENERIC_ERROR in response.data
    with client.session_transaction() as sess:
        assert "user_id" not in sess


def test_unknown_email_shows_the_same_message(client):
    """An unknown email must not be distinguishable from a wrong password."""
    response = login(client, email="nobody@spendly.com")
    assert response.status_code == 200
    assert GENERIC_ERROR in response.data
    with client.session_transaction() as sess:
        assert "user_id" not in sess


def test_wrong_password_and_unknown_email_read_identically(client):
    """Same wording for both, so neither leaks which addresses have accounts."""
    wrong_password = login(client, password="nope").data
    unknown_email = login(client, email="nobody@spendly.com").data
    assert GENERIC_ERROR in wrong_password
    assert GENERIC_ERROR in unknown_email


def test_rejected_login_keeps_the_email(client):
    response = login(client, password="nope")
    assert DEMO_EMAIL.encode() in response.data


def test_rejected_login_never_echoes_the_password(client):
    response = login(client, password="hunter2secret")
    assert b"hunter2secret" not in response.data


# ------------------------------------------------------------------ #
# Sessions: logout and the already-signed-in shortcut                 #
# ------------------------------------------------------------------ #

def test_logout_clears_the_session_and_redirects(client):
    login(client)
    response = client.get("/logout")
    assert response.status_code == 302
    assert response.headers["Location"] in ("/", "http://localhost/")
    with client.session_transaction() as sess:
        assert "user_id" not in sess


def test_logout_reverts_the_nav(client):
    login(client)
    client.get("/logout")
    landed = client.get("/")
    assert b"Sign in" in landed.data
    assert b"Get started" in landed.data


def test_logout_while_logged_out_is_harmless(client):
    response = client.get("/logout")
    assert response.status_code == 302
    assert response.headers["Location"] in ("/", "http://localhost/")


def test_get_login_while_logged_in_redirects_home(client):
    login(client)
    response = client.get("/login")
    assert response.status_code == 302
    assert response.headers["Location"] in ("/", "http://localhost/")
