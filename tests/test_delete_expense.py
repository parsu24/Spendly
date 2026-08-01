"""Tests for the Step 9 delete-expense route.

Covers GET/POST /expenses/<id>/delete. Step 8 already proved the ownership shape
this route reuses, so the centre of gravity here is different: **the GET must not
destroy anything**. The route was a bare `@app.route(...)` until this step — GET-only
by omission — and the tests that matter most below are the ones asserting the row
survives a request that merely looked at it.

The second theme is blast radius. A delete that removes the right row is only half
the requirement; it must also leave every other row, and the account itself, alone.
Several tests here count across *all* accounts rather than just the demo user's, for
exactly that reason.
"""

from datetime import date

import pytest

from app import app
from database import db


@pytest.fixture
def client(tmp_path, monkeypatch):
    """A test client whose database is a throwaway file with the demo account.

    Same trick as test_edit_expense.py: app.py binds get_db by reference at import
    time, but get_db reads the module-level DB_PATH when it is *called*, so patching
    the attribute here redirects the route's reads and writes to the temporary file
    too — no test can damage spendly.db.
    """
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    db.init_db()
    db.seed_db()
    app.config["TESTING"] = True
    return app.test_client()


DEMO_EMAIL = "demo@spendly.com"
DEMO_PASSWORD = "demo123"

# seed_db() always inserts the demo account first, so it holds id 1, with eight
# expenses totalling ₹18,240.
DEMO_ID = 1
SEEDED_COUNT = 8

TODAY = date.today().isoformat()


def login(client, email=DEMO_EMAIL, password=DEMO_PASSWORD):
    return client.post("/login", data={"email": email, "password": password})


def register(client, name, email, password="a-good-password"):
    """Create a second account, so a test has someone else's rows to protect."""
    return client.post(
        "/register", data={"name": name, "email": email, "password": password}
    )


def row(id=1):
    """One expense, whoever owns it."""
    conn = db.get_db()
    try:
        return conn.execute("SELECT * FROM expenses WHERE id = ?", (id,)).fetchone()
    finally:
        conn.close()


def expense_count(user_id=DEMO_ID):
    conn = db.get_db()
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM expenses WHERE user_id = ?", (user_id,)
        ).fetchone()[0]
    finally:
        conn.close()


def all_expenses():
    """Every row in the table, across every account — the blast-radius measure."""
    conn = db.get_db()
    try:
        return conn.execute("SELECT COUNT(*) FROM expenses").fetchone()[0]
    finally:
        conn.close()


def user_count():
    conn = db.get_db()
    try:
        return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    finally:
        conn.close()


def total(user_id=DEMO_ID):
    conn = db.get_db()
    try:
        return conn.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM expenses WHERE user_id = ?",
            (user_id,),
        ).fetchone()[0]
    finally:
        conn.close()


# Werkzeug has returned both relative and absolute Location headers across
# versions; every redirect assertion here tolerates either.
def assert_redirects_to_profile(response):
    assert response.status_code == 302
    target = response.headers["Location"].split("?")[0]
    assert target in ("/profile", "http://localhost/profile")


def assert_redirects_to_login(response):
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


# ------------------------------------------------------------------ #
# The GET must not delete — the point of this step                    #
# ------------------------------------------------------------------ #

def test_get_renders_a_confirmation_and_deletes_nothing(client):
    """The single most important test in this file.

    A destructive GET fires on a link prefetch, a crawler or a restored tab. Loading
    the confirmation must leave the table exactly as it was.
    """
    login(client)
    before = all_expenses()

    response = client.get(f"/expenses/{DEMO_ID}/delete")

    assert response.status_code == 200
    assert row(DEMO_ID) is not None
    assert all_expenses() == before


def test_repeated_gets_still_delete_nothing(client):
    """A prefetch is not always a single request."""
    login(client)
    for _ in range(3):
        assert client.get(f"/expenses/{DEMO_ID}/delete").status_code == 200
    assert expense_count() == SEEDED_COUNT


def test_the_confirmation_names_the_row(client):
    """Everything needed to retype the expense is on the screen before it goes —
    which is the reason this route asks for no password."""
    login(client)
    body = client.get(f"/expenses/{DEMO_ID}/delete").get_data(as_text=True)

    assert "₹3,450" in body            # the seeded groceries row, Indian grouping
    assert "Food" in body
    assert "Monthly groceries" in body
    assert "$" not in body


def test_a_null_description_renders_a_dash(client):
    """Not the word "None", not an empty gap, and no traceback."""
    login(client)
    client.post(
        "/expenses/add",
        data={"amount": "120", "category": "Other", "date": TODAY, "description": ""},
    )
    id = row_id_of_last()

    body = client.get(f"/expenses/{id}/delete").get_data(as_text=True)

    assert row(id)["description"] is None
    assert "—" in body
    assert "None" not in body


def row_id_of_last():
    conn = db.get_db()
    try:
        return conn.execute(
            "SELECT id FROM expenses ORDER BY id DESC LIMIT 1"
        ).fetchone()[0]
    finally:
        conn.close()


# ------------------------------------------------------------------ #
# The POST deletes exactly one row                                    #
# ------------------------------------------------------------------ #

def test_post_deletes_the_row_and_redirects(client):
    login(client)

    response = client.post(f"/expenses/{DEMO_ID}/delete")

    assert_redirects_to_profile(response)
    assert "deleted=1" in response.headers["Location"]
    assert row(DEMO_ID) is None
    assert expense_count() == SEEDED_COUNT - 1


def test_the_total_falls_by_the_deleted_amount(client):
    """₹18,240 less the ₹3,450 groceries row."""
    login(client)
    client.post(f"/expenses/{DEMO_ID}/delete")
    assert total() == 14790.0


def test_the_success_notice_shows_on_the_redirect_target(client):
    login(client)
    response = client.post(f"/expenses/{DEMO_ID}/delete", follow_redirects=True)
    assert "Your expense has been deleted." in response.get_data(as_text=True)


def test_blast_radius_is_one_row(client):
    """The account survives, every other row survives, and so does the session."""
    # No login() first: /register redirects a signed-in visitor away, so logging in
    # here would silently skip creating the second account and file its expense
    # under the demo user instead — leaving this test passing with nothing to guard.
    id = other_accounts_expense(client)      # leaves us logged in as the demo user
    before_all = all_expenses()
    before_users = user_count()

    client.post(f"/expenses/{DEMO_ID}/delete")

    assert all_expenses() == before_all - 1
    assert user_count() == before_users == 2
    assert row(id) is not None               # the other account is untouched
    # Deleting an expense must not sign anyone out.
    with client.session_transaction() as sess:
        assert sess["user_id"] == DEMO_ID


def test_deleting_every_row_empties_only_that_account(client):
    """No statement here may widen to `WHERE user_id = ?` without an id."""
    # No login() first, for the reason test_blast_radius_is_one_row gives.
    other = other_accounts_expense(client)

    for id in demo_expense_ids():
        assert_redirects_to_profile(client.post(f"/expenses/{id}/delete"))

    assert expense_count() == 0
    assert row(other) is not None
    assert user_count() == 2


def demo_expense_ids():
    conn = db.get_db()
    try:
        return [
            r[0] for r in conn.execute(
                "SELECT id FROM expenses WHERE user_id = ?", (DEMO_ID,)
            ).fetchall()
        ]
    finally:
        conn.close()


def test_the_empty_state_returns_after_the_last_delete(client):
    """The first-run state, not the filtered one — no range was applied."""
    login(client)
    for id in demo_expense_ids():
        client.post(f"/expenses/{id}/delete")

    body = client.get("/profile").get_data(as_text=True)
    assert "No expenses yet" in body
    assert "Your expenses" not in body


# ------------------------------------------------------------------ #
# Access control                                                      #
# ------------------------------------------------------------------ #

def test_get_requires_login(client):
    """A redirect, not a 404 — answering "not found" to a stranger would tell them
    which ids exist without their signing in at all."""
    assert_redirects_to_login(client.get(f"/expenses/{DEMO_ID}/delete"))


def test_post_requires_login_and_deletes_nothing(client):
    before = all_expenses()
    assert_redirects_to_login(client.post(f"/expenses/{DEMO_ID}/delete"))
    assert row(DEMO_ID) is not None
    assert all_expenses() == before


def test_a_logged_out_request_for_a_missing_id_still_redirects(client):
    """Identity is settled before the row is looked up, so the response cannot
    depend on whether the id exists."""
    assert_redirects_to_login(client.get("/expenses/99999/delete"))


def test_a_stale_session_clears_itself(client):
    """A cookie pointing at a user the rebuilt database no longer has."""
    with client.session_transaction() as sess:
        sess["user_id"] = 999
        sess["name"] = "Ghost"

    assert_redirects_to_login(client.get(f"/expenses/{DEMO_ID}/delete"))
    with client.session_transaction() as sess:
        assert "user_id" not in sess


def test_a_stale_session_cannot_delete(client):
    with client.session_transaction() as sess:
        sess["user_id"] = 999

    assert_redirects_to_login(client.post(f"/expenses/{DEMO_ID}/delete"))
    assert row(DEMO_ID) is not None


# ------------------------------------------------------------------ #
# Ownership                                                           #
# ------------------------------------------------------------------ #

def other_accounts_expense(client):
    """Register a second account, log it in, give it one expense, return its id.

    Leaves the client logged in as the demo user, which is the account every
    ownership test below attacks from.
    """
    register(client, "Asha Rao", "asha@spendly.com")
    login(client, email="asha@spendly.com", password="a-good-password")
    client.post(
        "/expenses/add",
        data={"amount": "500", "category": "Bills", "date": TODAY,
              "description": "Asha's water bill"},
    )
    id = row_id_of_last()
    login(client)
    return id


def test_another_accounts_expense_is_not_viewable(client):
    id = other_accounts_expense(client)
    assert client.get(f"/expenses/{id}/delete").status_code == 404


def test_another_accounts_expense_is_not_deletable(client):
    """The status code alone cannot tell a refused delete from a silent one."""
    id = other_accounts_expense(client)

    assert client.post(f"/expenses/{id}/delete").status_code == 404
    assert row(id) is not None


def test_a_nonexistent_id_is_the_same_404(client):
    """Same answer for an id that is somebody else's and one never issued — the
    difference would let a stranger walk the ids and count the table."""
    login(client)
    assert client.get("/expenses/99999/delete").status_code == 404
    assert client.post("/expenses/99999/delete").status_code == 404


def test_resubmitting_a_completed_delete_is_a_404_not_a_500(client):
    """The browser's back button lands on a confirmation whose row has gone."""
    login(client)
    assert_redirects_to_profile(client.post(f"/expenses/{DEMO_ID}/delete"))

    assert client.post(f"/expenses/{DEMO_ID}/delete").status_code == 404
    assert expense_count() == SEEDED_COUNT - 1


def test_a_form_user_id_cannot_redirect_the_delete(client):
    """The id in the path names a row; it does not name an owner."""
    id = other_accounts_expense(client)

    client.post(f"/expenses/{DEMO_ID}/delete", data={"user_id": 2, "id": id})

    assert row(DEMO_ID) is None      # the URL's row, and only it
    assert row(id) is not None       # the other account's row survives


# ------------------------------------------------------------------ #
# Escaping                                                            #
# ------------------------------------------------------------------ #

def test_a_sql_shaped_description_is_inert_and_escaped(client):
    """Stored verbatim, rendered as text, and its deletion leaves the table."""
    login(client)
    payload = "'); DROP TABLE expenses; --"
    client.post(
        "/expenses/add",
        data={"amount": "75", "category": "Other", "date": TODAY,
              "description": payload},
    )
    id = row_id_of_last()

    body = client.get(f"/expenses/{id}/delete").get_data(as_text=True)
    assert "DROP TABLE" in body
    assert "&#39;); DROP TABLE" in body      # escaped, not markup

    assert_redirects_to_profile(client.post(f"/expenses/{id}/delete"))
    assert expense_count() == SEEDED_COUNT   # the table is still there
