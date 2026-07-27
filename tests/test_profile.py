"""Tests for the Step 4 profile page."""

import pytest

from app import app
from database import db


@pytest.fixture
def client(tmp_path, monkeypatch):
    """A test client whose database is a throwaway file with the demo account.

    Same trick as test_login.py: app.py binds get_db by reference at import
    time, but get_db reads the module-level DB_PATH when it is *called*, so
    patching the attribute here redirects the route's reads too.
    """
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    db.init_db()
    db.seed_db()
    app.config["TESTING"] = True
    return app.test_client()


DEMO_EMAIL = "demo@spendly.com"
DEMO_PASSWORD = "demo123"

# seed_db() inserts eight expenses totalling this, with Food the largest slice.
SEEDED_TOTAL = "₹18,240"
SEEDED_FOOD = "₹6,630"


def login(client, email=DEMO_EMAIL, password=DEMO_PASSWORD):
    """POST the login form."""
    return client.post("/login", data={"email": email, "password": password})


def profile_text(client):
    """GET /profile as text — the rupee symbol is multi-byte, so decode it."""
    return client.get("/profile").get_data(as_text=True)


# ------------------------------------------------------------------ #
# Access control                                                      #
# ------------------------------------------------------------------ #

def test_profile_requires_login(client):
    response = client.get("/profile")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_logged_out_profile_leaks_nothing(client):
    """The redirect body must not carry the account it refused to show."""
    body = client.get("/profile").get_data(as_text=True)
    assert DEMO_EMAIL not in body
    assert SEEDED_TOTAL not in body


def test_profile_renders_for_a_signed_in_user(client):
    login(client)
    response = client.get("/profile")
    assert response.status_code == 200


def test_stale_session_is_cleared_not_crashed(client):
    """A cookie pointing at a user the rebuilt database no longer has."""
    with client.session_transaction() as sess:
        sess["user_id"] = 999
        sess["name"] = "Ghost"

    response = client.get("/profile")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]
    with client.session_transaction() as sess:
        assert "user_id" not in sess


# ------------------------------------------------------------------ #
# The account header                                                  #
# ------------------------------------------------------------------ #

def test_profile_shows_the_account_details(client):
    login(client)
    body = profile_text(client)
    assert "Demo User" in body
    assert DEMO_EMAIL in body
    assert "Member since" in body


def test_profile_never_exposes_the_password_hash(client):
    login(client)
    body = profile_text(client)
    assert "pbkdf2" not in body
    assert "scrypt" not in body


def test_nav_name_links_to_the_profile(client):
    login(client)
    landed = client.get("/").get_data(as_text=True)
    assert 'href="/profile"' in landed


# ------------------------------------------------------------------ #
# The summary figures                                                 #
# ------------------------------------------------------------------ #

def test_total_spent_is_formatted_in_rupees(client):
    login(client)
    body = profile_text(client)
    assert SEEDED_TOTAL in body
    assert "$" not in body
    assert "18240.0" not in body


def test_expense_count_is_shown(client):
    login(client)
    body = profile_text(client)
    assert "Expenses recorded" in body
    assert ">8<" in body


def test_top_category_is_food(client):
    login(client)
    body = profile_text(client)
    assert "Top category" in body
    assert ">Food<" in body


def test_category_breakdown_totals(client):
    login(client)
    body = profile_text(client)
    for category in ("Food", "Shopping", "Transport", "Bills",
                     "Health", "Other", "Entertainment"):
        assert category in body
    assert SEEDED_FOOD in body


def test_breakdown_is_ordered_largest_first(client):
    login(client)
    body = profile_text(client)
    positions = [body.index(name) for name in ("Shopping", "Transport", "Entertainment")]
    assert positions == sorted(positions)


def test_the_widest_bar_belongs_to_the_top_category(client):
    login(client)
    body = profile_text(client)
    assert "width: 100.0%" in body


# ------------------------------------------------------------------ #
# Scoping and the empty state                                         #
# ------------------------------------------------------------------ #

def register(client, name, email, password="a-good-password"):
    return client.post(
        "/register", data={"name": name, "email": email, "password": password}
    )


def test_a_new_account_sees_its_own_empty_profile(client):
    """A second user must not inherit the demo account's figures."""
    register(client, "Asha Rao", "asha@spendly.com")
    login(client, email="asha@spendly.com", password="a-good-password")

    body = profile_text(client)
    assert "Asha Rao" in body
    assert "No expenses yet" in body
    assert SEEDED_TOTAL not in body
    assert "Demo User" not in body


# ------------------------------------------------------------------ #
# The dynamic /profile/<id> route                                     #
# ------------------------------------------------------------------ #

def test_dynamic_route_renders_your_own_profile(client):
    """/profile/<your id> is the same page as /profile."""
    login(client)
    with client.session_transaction() as sess:
        user_id = sess["user_id"]

    response = client.get(f"/profile/{user_id}")
    assert response.status_code == 200
    assert response.get_data(as_text=True) == profile_text(client)


def test_dynamic_route_requires_login(client):
    """Guarded before the id is looked at, like every other profile route."""
    response = client.get("/profile/1")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_dynamic_route_refuses_another_users_id(client):
    """The id in the URL may name the session's account and nothing else."""
    register(client, "Asha Rao", "asha@spendly.com")
    login(client)                      # signed in as the demo account
    with client.session_transaction() as sess:
        mine = sess["user_id"]

    other = mine + 1                   # the account registered just above
    response = client.get(f"/profile/{other}")
    assert response.status_code == 404


def test_refused_id_leaks_nothing_about_that_account(client):
    """404, and a body that does not confirm the account exists."""
    register(client, "Asha Rao", "asha@spendly.com")
    login(client)
    with client.session_transaction() as sess:
        other = sess["user_id"] + 1

    body = client.get(f"/profile/{other}").get_data(as_text=True)
    assert "Asha Rao" not in body
    assert "asha@spendly.com" not in body


def test_unknown_id_is_indistinguishable_from_a_forbidden_one(client):
    """An id nobody holds answers exactly as another user's id does."""
    login(client)
    with client.session_transaction() as sess:
        mine = sess["user_id"]

    assert client.get(f"/profile/{mine + 999}").status_code == 404


def test_dynamic_route_does_not_shadow_the_static_subroutes(client):
    """<int:...> matches digits only, so /profile/edit still reaches its form."""
    login(client)
    response = client.get("/profile/edit")
    assert response.status_code == 200
    assert "Edit" in response.get_data(as_text=True)
