"""Tests for the Step 5 account-management routes.

Covers /profile/edit, /profile/password and /profile/delete: the access
control every one of them repeats, the validation each applies, and the
database effects — a route that renders correctly but writes the wrong row,
or writes nothing at all, is the failure this file exists to catch.
"""

import pytest

from app import app
from database import db


@pytest.fixture
def client(tmp_path, monkeypatch):
    """A test client whose database is a throwaway file with the demo account.

    Same trick as test_profile.py: app.py binds get_db by reference at import
    time, but get_db reads the module-level DB_PATH when it is *called*, so
    patching the attribute here redirects the route's reads and writes to the
    temporary file too — no test can damage spendly.db.
    """
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    db.init_db()
    db.seed_db()
    app.config["TESTING"] = True
    return app.test_client()


DEMO_EMAIL = "demo@spendly.com"
DEMO_PASSWORD = "demo123"
DEMO_NAME = "Demo User"

# seed_db() always inserts the demo account first, so it holds id 1.
DEMO_ID = 1


def login(client, email=DEMO_EMAIL, password=DEMO_PASSWORD):
    """POST the login form."""
    return client.post("/login", data={"email": email, "password": password})


def register(client, name, email, password="a-good-password"):
    """Create a second account, so a test has someone else to collide with."""
    return client.post(
        "/register", data={"name": name, "email": email, "password": password}
    )


def fetch_user(user_id=DEMO_ID):
    """Read a user row straight from the database, bypassing the routes.

    Asserting on the response alone cannot tell a rejected write from a
    silently successful one, so every mutation test checks the row itself.
    """
    conn = db.get_db()
    try:
        return conn.execute(
            "SELECT * FROM users WHERE id = ?", (user_id,)
        ).fetchone()
    finally:
        conn.close()


def expense_count(user_id=DEMO_ID):
    """How many expenses that account still owns."""
    conn = db.get_db()
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM expenses WHERE user_id = ?", (user_id,)
        ).fetchone()[0]
    finally:
        conn.close()


# Werkzeug has returned both relative and absolute Location headers across
# versions; every redirect assertion here tolerates either.
def assert_redirects_to_profile(response):
    """The success notice rides on the query string, so compare the path only."""
    assert response.status_code == 302
    target = response.headers["Location"].split("?")[0]
    assert target in ("/profile", "http://localhost/profile")


def assert_redirects_to_login(response):
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


# ------------------------------------------------------------------ #
# Edit — access control                                               #
# ------------------------------------------------------------------ #

def test_edit_get_requires_login(client):
    assert_redirects_to_login(client.get("/profile/edit"))


def test_edit_post_requires_login(client):
    """The guard must run before any form parsing — anything can POST here."""
    response = client.post(
        "/profile/edit", data={"name": "Intruder", "email": "intruder@spendly.com"}
    )
    assert_redirects_to_login(response)

    user = fetch_user()
    assert user["name"] == DEMO_NAME
    assert user["email"] == DEMO_EMAIL


def test_logged_out_edit_leaks_nothing(client):
    """The refusal must not carry the account it declined to show."""
    body = client.get("/profile/edit").get_data(as_text=True)
    assert DEMO_EMAIL not in body
    assert DEMO_NAME not in body


def test_edit_with_a_stale_session_clears_it(client):
    """A cookie pointing at a user the rebuilt database no longer has."""
    with client.session_transaction() as sess:
        sess["user_id"] = 999
        sess["name"] = "Ghost"

    assert_redirects_to_login(client.get("/profile/edit"))
    with client.session_transaction() as sess:
        assert "user_id" not in sess


# ------------------------------------------------------------------ #
# Edit — the form                                                     #
# ------------------------------------------------------------------ #

def test_edit_form_is_prefilled(client):
    login(client)
    body = client.get("/profile/edit").get_data(as_text=True)
    assert 'value="Demo User"' in body
    assert 'value="demo@spendly.com"' in body


def test_edit_form_carries_no_hidden_id(client):
    """The row to update comes from the session, never from the page."""
    login(client)
    body = client.get("/profile/edit").get_data(as_text=True)
    assert 'type="hidden"' not in body


def test_edit_form_has_no_dollar_signs(client):
    login(client)
    body = client.get("/profile/edit").get_data(as_text=True)
    assert "$" not in body
    assert "USD" not in body


# ------------------------------------------------------------------ #
# Edit — saving                                                       #
# ------------------------------------------------------------------ #

def test_saving_a_new_name_updates_the_row(client):
    login(client)
    response = client.post(
        "/profile/edit", data={"name": "Demo Owner", "email": DEMO_EMAIL}
    )
    assert_redirects_to_profile(response)
    assert fetch_user()["name"] == "Demo Owner"


def test_saving_a_new_name_refreshes_the_session(client):
    login(client)
    client.post("/profile/edit", data={"name": "Demo Owner", "email": DEMO_EMAIL})
    with client.session_transaction() as sess:
        assert sess["name"] == "Demo Owner"


def test_saving_a_new_name_updates_the_nav(client):
    """base.html renders session.name; the header must not lag until re-login."""
    login(client)
    client.post("/profile/edit", data={"name": "Demo Owner", "email": DEMO_EMAIL})
    assert b"Demo Owner" in client.get("/").data
    assert b"Demo User" not in client.get("/").data


def test_the_name_is_stored_and_shown_stripped(client):
    login(client)
    client.post(
        "/profile/edit", data={"name": "  Demo Owner  ", "email": DEMO_EMAIL}
    )
    assert fetch_user()["name"] == "Demo Owner"
    with client.session_transaction() as sess:
        assert sess["name"] == "Demo Owner"


def test_a_successful_edit_confirms_itself(client):
    """Following the redirect proves the route sets the notice parameter."""
    login(client)
    response = client.post(
        "/profile/edit",
        data={"name": "Demo Owner", "email": DEMO_EMAIL},
        follow_redirects=True,
    )
    body = response.get_data(as_text=True)
    assert "Your profile has been updated." in body
    assert "Demo Owner" in body


def test_the_profile_links_to_the_edit_form(client):
    login(client)
    assert 'href="/profile/edit"' in client.get("/profile").get_data(as_text=True)


def test_saving_without_changing_the_email_succeeds(client):
    """The duplicate check must exclude your own row, or this reports a clash."""
    login(client)
    response = client.post(
        "/profile/edit", data={"name": "Demo Owner", "email": DEMO_EMAIL}
    )
    assert_redirects_to_profile(response)
    assert fetch_user()["email"] == DEMO_EMAIL


def test_the_email_can_be_changed(client):
    login(client)
    response = client.post(
        "/profile/edit", data={"name": DEMO_NAME, "email": "owner@spendly.com"}
    )
    assert_redirects_to_profile(response)
    assert fetch_user()["email"] == "owner@spendly.com"


def test_the_email_is_normalised_to_lowercase(client):
    """Otherwise SQLite's case-sensitive TEXT lets one address become two."""
    login(client)
    client.post(
        "/profile/edit", data={"name": DEMO_NAME, "email": "  DEMO@Spendly.com  "}
    )
    assert fetch_user()["email"] == DEMO_EMAIL


def test_created_at_survives_an_edit(client):
    """"Member since" is not allowed to move because a name changed."""
    login(client)
    before = fetch_user()["created_at"]
    client.post(
        "/profile/edit", data={"name": "Demo Owner", "email": "owner@spendly.com"}
    )
    assert fetch_user()["created_at"] == before


def test_an_edit_touches_no_expenses(client):
    login(client)
    client.post("/profile/edit", data={"name": "Demo Owner", "email": DEMO_EMAIL})
    assert expense_count() == 8


# ------------------------------------------------------------------ #
# Edit — rejections                                                   #
# ------------------------------------------------------------------ #

def test_another_accounts_email_is_rejected(client):
    register(client, "Asha Rao", "asha@spendly.com")
    login(client)

    response = client.post(
        "/profile/edit", data={"name": DEMO_NAME, "email": "asha@spendly.com"}
    )
    assert response.status_code == 200
    assert b"already exists" in response.data
    assert fetch_user()["email"] == DEMO_EMAIL


def test_a_blank_name_is_rejected(client):
    login(client)
    response = client.post(
        "/profile/edit", data={"name": "   ", "email": DEMO_EMAIL}
    )
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Please fill in every field." in body
    # The field the visitor got right is still filled in.
    assert 'value="demo@spendly.com"' in body
    assert fetch_user()["name"] == DEMO_NAME


def test_a_blank_email_is_rejected(client):
    login(client)
    response = client.post("/profile/edit", data={"name": "Demo Owner", "email": ""})
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Please fill in every field." in body
    assert 'value="Demo Owner"' in body
    assert fetch_user()["email"] == DEMO_EMAIL


def test_a_malformed_email_is_rejected(client):
    login(client)
    response = client.post(
        "/profile/edit", data={"name": "Demo Owner", "email": "not-an-email"}
    )
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Please enter a valid email address." in body
    assert 'value="Demo Owner"' in body
    assert fetch_user()["email"] == DEMO_EMAIL


def test_a_rejected_edit_leaves_the_nav_alone(client):
    """session["name"] belongs on the success path only."""
    login(client)
    client.post("/profile/edit", data={"name": "Ghost", "email": "not-an-email"})

    with client.session_transaction() as sess:
        assert sess["name"] == DEMO_NAME
    assert b"Ghost" not in client.get("/").data


# ------------------------------------------------------------------ #
# Password — access control                                           #
# ------------------------------------------------------------------ #

NEW_PASSWORD = "a-brand-new-password"


def change_password(client, current, new, confirm=None):
    """POST the change-password form; `confirm` defaults to matching `new`."""
    return client.post(
        "/profile/password",
        data={
            "current_password": current,
            "new_password": new,
            "confirm_password": new if confirm is None else confirm,
        },
    )


def test_password_get_requires_login(client):
    assert_redirects_to_login(client.get("/profile/password"))


def test_password_post_requires_login(client):
    """The guard must run before any form parsing — anything can POST here."""
    before = fetch_user()["password_hash"]
    assert_redirects_to_login(change_password(client, DEMO_PASSWORD, NEW_PASSWORD))
    assert fetch_user()["password_hash"] == before


def test_password_with_a_stale_session_clears_it(client):
    """A cookie pointing at a user the rebuilt database no longer has."""
    with client.session_transaction() as sess:
        sess["user_id"] = 999
        sess["name"] = "Ghost"

    assert_redirects_to_login(client.get("/profile/password"))
    with client.session_transaction() as sess:
        assert "user_id" not in sess


# ------------------------------------------------------------------ #
# Password — the form                                                 #
# ------------------------------------------------------------------ #

def test_password_form_prefills_nothing(client):
    """Every field here is a password, so none may arrive with a value."""
    login(client)
    body = client.get("/profile/password").get_data(as_text=True)
    assert "value=" not in body.split('<form method="POST"')[1].split("</form>")[0]


def test_password_form_never_renders_the_hash(client):
    """The stored credential is read for verification only, never templated."""
    login(client)
    body = client.get("/profile/password").get_data(as_text=True)
    assert "pbkdf2" not in body
    assert "scrypt" not in body


def test_password_form_has_no_dollar_signs(client):
    login(client)
    body = client.get("/profile/password").get_data(as_text=True)
    assert "$" not in body
    assert "USD" not in body


def test_the_profile_links_to_the_password_form(client):
    login(client)
    assert 'href="/profile/password"' in client.get("/profile").get_data(as_text=True)


# ------------------------------------------------------------------ #
# Password — changing it                                              #
# ------------------------------------------------------------------ #

def test_a_correct_change_redirects_and_rewrites_the_hash(client):
    login(client)
    before = fetch_user()["password_hash"]
    assert_redirects_to_profile(change_password(client, DEMO_PASSWORD, NEW_PASSWORD))
    assert fetch_user()["password_hash"] != before


def test_after_a_change_only_the_new_password_signs_in(client):
    """The real proof: the response body could lie, the login form cannot."""
    login(client)
    change_password(client, DEMO_PASSWORD, NEW_PASSWORD)
    client.get("/logout")

    assert login(client, password=DEMO_PASSWORD).status_code == 200
    with client.session_transaction() as sess:
        assert "user_id" not in sess

    assert login(client, password=NEW_PASSWORD).status_code == 302
    with client.session_transaction() as sess:
        assert sess["user_id"] == DEMO_ID


def test_a_successful_change_keeps_you_signed_in(client):
    """Changing your own password is no reason to be logged out of this browser."""
    login(client)
    change_password(client, DEMO_PASSWORD, NEW_PASSWORD)
    with client.session_transaction() as sess:
        assert sess["user_id"] == DEMO_ID
        assert sess["name"] == DEMO_NAME


def test_a_successful_change_confirms_itself(client):
    login(client)
    response = change_password(
        client, DEMO_PASSWORD, NEW_PASSWORD
    )
    assert "password=1" in response.headers["Location"]

    body = client.get(response.headers["Location"]).get_data(as_text=True)
    assert "Your password has been changed." in body


def test_a_change_touches_nothing_else(client):
    login(client)
    before = fetch_user()
    change_password(client, DEMO_PASSWORD, NEW_PASSWORD)
    after = fetch_user()

    assert after["name"] == before["name"]
    assert after["email"] == before["email"]
    assert after["created_at"] == before["created_at"]
    assert expense_count() == 8


# ------------------------------------------------------------------ #
# Password — rejections                                               #
# ------------------------------------------------------------------ #

def test_a_wrong_current_password_is_rejected(client):
    """Asserting the message alone would pass even if the write happened anyway,
    so this logs out and proves the old password still opens the account."""
    login(client)
    response = change_password(client, "not-the-password", NEW_PASSWORD)

    assert response.status_code == 200
    assert "Your current password is not correct." in response.get_data(as_text=True)

    client.get("/logout")
    assert login(client, password=DEMO_PASSWORD).status_code == 302
    client.get("/logout")
    assert login(client, password=NEW_PASSWORD).status_code == 200


def test_a_wrong_current_password_is_reported_specifically(client):
    """The visitor is already authenticated, so there is no enumeration to
    protect against and login's deliberately vague wording is not reused."""
    login(client)
    body = change_password(client, "not-the-password", NEW_PASSWORD).get_data(
        as_text=True
    )
    assert "Incorrect email or password." not in body


def test_re_authentication_precedes_the_shape_checks(client):
    """A bad current password is reported as such however malformed the rest is."""
    login(client)
    body = change_password(client, "not-the-password", "x", confirm="y").get_data(
        as_text=True
    )
    assert "Your current password is not correct." in body
    # The form's own hint says "Must be at least 8 characters."; only the error
    # sentence carries the "Password" prefix, so this cannot match it.
    assert "Password must be at least 8 characters." not in body


def test_a_short_new_password_is_rejected(client):
    login(client)
    before = fetch_user()["password_hash"]
    response = change_password(client, DEMO_PASSWORD, "short1")

    assert response.status_code == 200
    assert "Password must be at least 8 characters." in response.get_data(as_text=True)
    assert fetch_user()["password_hash"] == before


def test_a_mismatched_confirmation_is_rejected(client):
    login(client)
    before = fetch_user()["password_hash"]
    response = change_password(
        client, DEMO_PASSWORD, NEW_PASSWORD, confirm="a-different-password"
    )

    assert response.status_code == 200
    assert "The new passwords do not match." in response.get_data(as_text=True)
    assert fetch_user()["password_hash"] == before


def test_reusing_the_current_password_is_rejected(client):
    """Changed once first: the seeded demo123 is under 8 characters, so it would
    trip the length rule before ever reaching the sameness check."""
    login(client)
    change_password(client, DEMO_PASSWORD, NEW_PASSWORD)
    before = fetch_user()["password_hash"]

    response = change_password(client, NEW_PASSWORD, NEW_PASSWORD)
    assert response.status_code == 200
    assert "must be different" in response.get_data(as_text=True)
    assert fetch_user()["password_hash"] == before


def test_a_blank_field_is_rejected(client):
    login(client)
    before = fetch_user()["password_hash"]

    for data in (
        {"current_password": "", "new_password": NEW_PASSWORD,
         "confirm_password": NEW_PASSWORD},
        {"current_password": DEMO_PASSWORD, "new_password": "",
         "confirm_password": NEW_PASSWORD},
        {"current_password": DEMO_PASSWORD, "new_password": NEW_PASSWORD,
         "confirm_password": ""},
    ):
        response = client.post("/profile/password", data=data)
        assert response.status_code == 200
        assert "Please fill in every field." in response.get_data(as_text=True)

    assert fetch_user()["password_hash"] == before


def test_passwords_are_never_stripped(client):
    """Surrounding spaces are part of a password; trimming them would store
    something the visitor cannot type back in."""
    login(client)
    padded = "  spaced out password  "
    assert_redirects_to_profile(change_password(client, DEMO_PASSWORD, padded))

    client.get("/logout")
    assert login(client, password=padded.strip()).status_code == 200
    assert login(client, password=padded).status_code == 302


def test_a_rejected_change_never_echoes_a_password(client):
    """Mirrors test_login.py — no submitted secret may reach the HTML."""
    login(client)
    response = change_password(
        client, "wrong-hunter2secret", "new-hunter2secret", confirm="typo-hunter2secret"
    )
    body = response.get_data(as_text=True)

    assert "wrong-hunter2secret" not in body
    assert "new-hunter2secret" not in body
    assert "typo-hunter2secret" not in body


def test_a_rejected_change_keeps_you_signed_in(client):
    login(client)
    change_password(client, "not-the-password", NEW_PASSWORD)
    with client.session_transaction() as sess:
        assert sess["user_id"] == DEMO_ID


# ------------------------------------------------------------------ #
# Delete — access control                                             #
# ------------------------------------------------------------------ #

def delete_account(client, password=DEMO_PASSWORD):
    """POST the delete confirmation form."""
    return client.post("/profile/delete", data={"password": password})


def assert_redirects_to_landing(response):
    """Deletion ends on the marketing page, not on a profile that is gone."""
    assert response.status_code == 302
    assert response.headers["Location"] in ("/", "http://localhost/")


def test_delete_get_requires_login(client):
    assert_redirects_to_login(client.get("/profile/delete"))


def test_delete_post_requires_login(client):
    """The most important access-control test in the step: an anonymous POST
    carrying the right password must still be turned away at the guard, before
    the form is ever parsed — and must leave the account and its expenses
    exactly where they were."""
    assert_redirects_to_login(delete_account(client))

    assert fetch_user() is not None
    assert expense_count() == 8


def test_delete_with_a_stale_session_clears_it(client):
    """A cookie pointing at a user the rebuilt database no longer has."""
    with client.session_transaction() as sess:
        sess["user_id"] = 999
        sess["name"] = "Ghost"

    assert_redirects_to_login(client.get("/profile/delete"))
    with client.session_transaction() as sess:
        assert "user_id" not in sess


# ------------------------------------------------------------------ #
# Delete — the confirmation screen                                    #
# ------------------------------------------------------------------ #

def test_the_confirmation_states_the_consequence(client):
    """A warning without numbers is not informed consent. Decoded as text
    because the rupee sign is multi-byte and would not match against raw bytes."""
    login(client)
    body = client.get("/profile/delete").get_data(as_text=True)

    assert "8 expense" in body
    assert "₹18,240" in body
    assert "cannot be undone" in body


def test_the_confirmation_shows_no_dollar_signs(client):
    login(client)
    body = client.get("/profile/delete").get_data(as_text=True)
    assert "$" not in body
    assert "USD" not in body


def test_the_confirmation_never_renders_the_hash(client):
    """The stored credential is read for verification only, never templated."""
    login(client)
    body = client.get("/profile/delete").get_data(as_text=True)
    assert "pbkdf2" not in body
    assert "scrypt" not in body


def test_loading_the_confirmation_deletes_nothing(client):
    """A destructive action behind a GET fires on a prefetch or a crawler."""
    login(client)
    client.get("/profile/delete")

    assert fetch_user() is not None
    assert expense_count() == 8


def test_the_confirmation_handles_an_account_with_no_expenses(client):
    """The COALESCE in the summary query is what keeps this a page rather than
    a 500: without it the sum comes back NULL and the inr filter is handed None.
    Registered before logging in — /register turns a signed-in visitor away."""
    register(client, "Asha Rao", "asha@spendly.com")
    login(client, email="asha@spendly.com", password="a-good-password")

    response = client.get("/profile/delete")
    assert response.status_code == 200
    assert "no expenses recorded" in response.get_data(as_text=True)


def test_the_profile_links_to_the_delete_confirmation(client):
    login(client)
    assert 'href="/profile/delete"' in client.get("/profile").get_data(as_text=True)


# ------------------------------------------------------------------ #
# Delete — rejections                                                 #
# ------------------------------------------------------------------ #

def test_a_wrong_password_does_not_delete_the_account(client):
    login(client)
    response = delete_account(client, "not-the-password")

    assert response.status_code == 200
    assert "That password is not correct." in response.get_data(as_text=True)
    assert fetch_user() is not None
    assert expense_count() == 8


def test_a_wrong_password_keeps_you_signed_in(client):
    """The account survived, so the session covering it must survive too."""
    login(client)
    delete_account(client, "not-the-password")
    with client.session_transaction() as sess:
        assert sess["user_id"] == DEMO_ID


def test_a_blank_password_is_rejected(client):
    login(client)
    response = delete_account(client, "")

    assert response.status_code == 200
    assert "Please enter your password to confirm." in response.get_data(as_text=True)
    assert fetch_user() is not None


def test_a_rejected_delete_still_states_the_consequence(client):
    """The count and total are computed before the method branch; computing
    them inside the GET arm would make this re-render a 500."""
    login(client)
    body = delete_account(client, "not-the-password").get_data(as_text=True)

    assert "8 expense" in body
    assert "₹18,240" in body


def test_a_rejected_delete_never_echoes_the_password(client):
    login(client)
    body = delete_account(client, "wrong-hunter2secret").get_data(as_text=True)
    assert "wrong-hunter2secret" not in body


# ------------------------------------------------------------------ #
# Delete — deleting                                                   #
# ------------------------------------------------------------------ #

def test_a_correct_password_deletes_the_account(client):
    login(client)
    assert_redirects_to_landing(delete_account(client))
    assert fetch_user() is None


def test_deleting_clears_the_whole_session(client):
    """clear(), not pop("user_id") — session["name"] must not outlive the row."""
    login(client)
    delete_account(client)
    with client.session_transaction() as sess:
        assert "user_id" not in sess
        assert "name" not in sess


def test_after_deleting_the_profile_is_gone(client):
    login(client)
    delete_account(client)
    assert_redirects_to_login(client.get("/profile"))


def test_deleting_cascades_to_the_expenses(client):
    """The whole point of the exercise: one DELETE against users, and the
    expenses go with it. This is what proves PRAGMA foreign_keys = ON is in
    force — without it SQLite ignores the rule and orphans all eight rows."""
    login(client)
    delete_account(client)
    assert expense_count() == 0


def test_deleting_reverts_the_nav_to_signed_out(client):
    login(client)
    delete_account(client)
    body = client.get("/").get_data(as_text=True)

    assert "Sign in" in body
    assert "Get started" in body
    assert DEMO_NAME not in body


def test_the_deleted_account_can_no_longer_sign_in(client):
    login(client)
    delete_account(client)

    assert login(client).status_code == 200
    with client.session_transaction() as sess:
        assert "user_id" not in sess


def test_deleting_is_scoped_to_the_session_account(client):
    """The DELETE is bound to session["user_id"], so nobody else's rows move —
    and the cascade takes exactly one account's expenses with it."""
    register(client, "Asha Rao", "asha@spendly.com")

    other = fetch_user(2)
    assert other is not None

    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO expenses (user_id, amount, category, date, description)"
            " VALUES (?, ?, ?, ?, ?)",
            (other["id"], 500.0, "Food", "2026-01-01", "Asha's lunch"),
        )
        conn.commit()
    finally:
        conn.close()

    login(client)
    assert_redirects_to_landing(delete_account(client))

    assert fetch_user() is None
    assert expense_count() == 0
    assert fetch_user(2) is not None
    assert expense_count(2) == 1
