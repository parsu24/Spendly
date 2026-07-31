"""Tests for the Step 8 edit-expense route.

Covers GET/POST /expenses/<id>/edit. This is the first route in the project where
a value from the URL names a database row, so the centre of gravity here is
ownership: an id belonging to somebody else, and an id belonging to nobody, must
both come back 404 and must leave the table alone.

The validation cases mirror tests/test_add_expense.py deliberately. Both routes
call parse_expense_form(), and running the same rejections against both is what
proves the shared helper did not quietly relax one of them for the edit form.

Every rejection asserts on the row itself, not only the response — a form that
renders its error correctly and writes anyway is the failure these tests exist to
catch.
"""

from datetime import date, timedelta

import pytest

from app import app
from database import db


@pytest.fixture
def client(tmp_path, monkeypatch):
    """A test client whose database is a throwaway file with the demo account.

    Same trick as test_add_expense.py: app.py binds get_db by reference at import
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


def edit(client, id=1, amount="4000", category="Food", day=None,
         description="Monthly groceries", **extra):
    """POST the edit form. `extra` appends fields the form never renders."""
    data = {
        "amount": amount,
        "category": category,
        "date": TODAY if day is None else day,
        "description": description,
    }
    data.update(extra)
    return client.post(f"/expenses/{id}/edit", data=data)


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


def reject(client, message, **kwargs):
    """POST an edit that must fail, and prove the row survived it untouched.

    The snapshot is taken inside this helper rather than passed in, so it cannot
    accidentally be read after the request that was supposed to be refused —
    which would compare the row against itself and pass no matter what.
    """
    id = kwargs.get("id", 1)
    before = tuple(row(id))

    response = edit(client, **kwargs)

    assert response.status_code == 200
    assert message in response.get_data(as_text=True)
    assert tuple(row(id)) == before
    return response


# ------------------------------------------------------------------ #
# Access control                                                      #
# ------------------------------------------------------------------ #

def test_get_requires_login(client):
    """A redirect, not a 404 — answering "not found" to a stranger would tell
    them which ids exist without their signing in at all."""
    response = client.get("/expenses/1/edit")
    assert_redirects_to_login(response)


def test_post_requires_login(client):
    """The guard must run before any form parsing — anything can POST here."""
    before = row(1)
    assert_redirects_to_login(edit(client))
    assert tuple(row(1)) == tuple(before)


def test_a_logged_out_request_for_a_missing_id_still_redirects(client):
    """Identity is settled before the row is looked up, so the response cannot
    depend on whether the id exists."""
    assert_redirects_to_login(client.get("/expenses/99999/edit"))


def test_a_stale_session_clears_itself(client):
    """A cookie pointing at a user the rebuilt database no longer has."""
    with client.session_transaction() as sess:
        sess["user_id"] = 999
        sess["name"] = "Ghost"

    assert_redirects_to_login(client.get("/expenses/1/edit"))
    with client.session_transaction() as sess:
        assert "user_id" not in sess


def test_a_stale_session_cannot_update(client):
    with client.session_transaction() as sess:
        sess["user_id"] = 999

    before = row(1)
    assert_redirects_to_login(edit(client))
    assert tuple(row(1)) == tuple(before)


# ------------------------------------------------------------------ #
# Ownership — the point of this step                                  #
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
    conn = db.get_db()
    try:
        id = conn.execute(
            "SELECT id FROM expenses ORDER BY id DESC LIMIT 1"
        ).fetchone()[0]
    finally:
        conn.close()

    login(client)
    return id


def test_another_accounts_expense_is_not_readable(client):
    id = other_accounts_expense(client)
    assert client.get(f"/expenses/{id}/edit").status_code == 404


def test_another_accounts_expense_is_not_writable(client):
    """The status code alone cannot tell a refused write from a silent one."""
    id = other_accounts_expense(client)
    before = row(id)

    assert edit(client, id=id, amount="99999").status_code == 404
    assert tuple(row(id)) == tuple(before)


def test_a_nonexistent_id_is_the_same_404(client):
    """Same answer as somebody else's id, so walking the ids reveals nothing
    about how many expenses the app holds."""
    login(client)
    assert client.get("/expenses/99999/edit").status_code == 404
    assert edit(client, id=99999).status_code == 404


def test_the_owner_cannot_be_reassigned_by_the_form(client):
    """A form that could name its owner is how one account takes another's row."""
    register(client, "Asha Rao", "asha@spendly.com")
    login(client)

    assert_redirects_to_profile(edit(client, id=1, user_id=2))
    assert row(1)["user_id"] == DEMO_ID
    assert expense_count(2) == 0


def test_an_id_in_the_form_cannot_redirect_the_write(client):
    """The URL names the row; a body field must not be able to name a different
    one."""
    login(client)
    before = tuple(row(2))

    # Posted straight rather than through edit(), whose own `id` argument is the
    # URL's — this needs the two to disagree.
    client.post(
        "/expenses/1/edit",
        data={"amount": "4000", "category": "Food", "date": TODAY,
              "description": "Monthly groceries", "id": 2},
    )

    assert tuple(row(2)) == before
    assert row(1)["amount"] == 4000.0


# ------------------------------------------------------------------ #
# The form                                                            #
# ------------------------------------------------------------------ #

def test_the_profile_links_to_every_row(client):
    login(client)
    body = client.get("/profile").get_data(as_text=True)

    for id in range(1, SEEDED_COUNT + 1):
        assert f'href="/expenses/{id}/edit"' in body


def test_the_form_is_prefilled_from_the_row(client):
    login(client)
    expense = row(1)
    body = client.get("/expenses/1/edit").get_data(as_text=True)

    assert f'value="{expense["date"]}"' in body
    assert f'value="{expense["category"]}" selected' in body
    assert f'value="{expense["description"]}"' in body
    # 3450.0 in the column, "3450" in the field — a whole-rupee row should not
    # read as "3450.0".
    assert 'value="3450"' in body


def test_the_form_offers_every_category_and_nothing_else(client):
    login(client)
    body = client.get("/expenses/1/edit").get_data(as_text=True)

    for category in db.CATEGORIES:
        assert f'value="{category}"' in body

    # Seven real options plus the disabled placeholder, and nothing invented.
    assert body.count("<option value=") == len(db.CATEGORIES) + 1


def test_the_form_carries_no_hidden_fields(client):
    """The row and its owner are settled by the URL and the session."""
    login(client)
    assert 'type="hidden"' not in client.get("/expenses/1/edit").get_data(as_text=True)


def test_the_form_posts_to_its_own_url(client):
    login(client)
    assert 'action="/expenses/1/edit"' in client.get(
        "/expenses/1/edit"
    ).get_data(as_text=True)


def test_the_form_has_no_dollar_signs(client):
    login(client)
    body = client.get("/expenses/1/edit").get_data(as_text=True)
    assert "$" not in body
    assert "USD" not in body


# ------------------------------------------------------------------ #
# Updating                                                            #
# ------------------------------------------------------------------ #

def test_an_edit_changes_the_row_and_creates_none(client):
    login(client)
    assert_redirects_to_profile(edit(client, id=1, amount="4000", category="Food"))

    assert row(1)["amount"] == 4000.0
    assert row(1)["category"] == "Food"
    # The whole distinction between this route and /expenses/add.
    assert expense_count() == SEEDED_COUNT


def test_the_totals_move(client):
    """3450 -> 4000 on a ₹18,240 account."""
    login(client)
    assert "₹18,240" in client.get("/profile").get_data(as_text=True)

    edit(client, id=1, amount="4000")
    body = client.get("/profile").get_data(as_text=True)

    assert "₹18,790" in body
    # The "Expenses recorded" tile still reads eight.
    assert ">8</span>" in body


def test_a_successful_edit_confirms_itself(client):
    login(client)
    response = edit(client)
    assert "edited=1" in response.headers["Location"]

    body = client.get(response.headers["Location"]).get_data(as_text=True)
    assert "Your expense has been updated." in body


def test_a_category_change_moves_the_row_between_bars(client):
    login(client)
    edit(client, id=1, category="Health")
    assert row(1)["category"] == "Health"


def test_saving_unchanged_values_succeeds(client):
    """Re-saving an expense unchanged is not a mistake worth an error."""
    login(client)
    before = row(1)

    assert_redirects_to_profile(edit(
        client, id=1,
        amount=str(before["amount"]),
        category=before["category"],
        day=before["date"],
        description=before["description"],
    ))
    assert tuple(row(1)) == tuple(before)


def test_created_at_survives_an_edit(client):
    """It records when the expense was entered, not when it was last touched."""
    login(client)
    before = row(1)["created_at"]

    edit(client, id=1, amount="4000")
    assert row(1)["created_at"] == before


def test_a_cleared_description_becomes_null(client):
    """The column is the one nullable field; a blank note is its absence."""
    login(client)
    assert_redirects_to_profile(edit(client, id=1, description=""))
    assert row(1)["description"] is None


def test_a_whitespace_description_becomes_null(client):
    login(client)
    edit(client, id=1, description="   ")
    assert row(1)["description"] is None


def test_a_decimal_amount_is_stored(client):
    login(client)
    edit(client, id=1, amount="99.50")
    assert row(1)["amount"] == 99.5


def test_an_over_precise_amount_is_rounded(client):
    """amount is REAL; storing unrounded input makes the totals drift."""
    login(client)
    edit(client, id=1, amount="99.999")
    assert row(1)["amount"] == 100.0


def test_a_past_date_is_accepted(client):
    login(client)
    day = (date.today() - timedelta(days=40)).isoformat()
    assert_redirects_to_profile(edit(client, id=1, day=day))
    assert row(1)["date"] == day


# ------------------------------------------------------------------ #
# Rejections — the same rules /expenses/add applies                   #
# ------------------------------------------------------------------ #

MISSING = "Please fill in every field."


def test_a_blank_amount_is_rejected(client):
    login(client)
    reject(client, MISSING, amount="")


def test_a_blank_category_is_rejected(client):
    login(client)
    reject(client, MISSING, category="")


def test_a_blank_date_is_rejected(client):
    login(client)
    reject(client, MISSING, day="")


def test_a_rejection_keeps_the_other_fields(client):
    """Fixing one field must not mean retyping the other three."""
    login(client)
    body = edit(
        client, amount="", category="Bills", description="Water bill"
    ).get_data(as_text=True)

    assert 'value="Bills" selected' in body
    assert 'value="Water bill"' in body
    assert f'value="{TODAY}"' in body


def test_a_rejection_still_posts_to_the_right_row(client):
    """The re-rendered form must carry its id, or a corrected submit would go
    nowhere."""
    login(client)
    body = edit(client, id=3, amount="").get_data(as_text=True)
    assert 'action="/expenses/3/edit"' in body


def test_zero_is_rejected(client):
    login(client)
    reject(client, "greater than zero", amount="0")


def test_a_negative_amount_is_rejected(client):
    login(client)
    reject(client, "greater than zero", amount="-50")


def test_a_non_numeric_amount_is_rejected(client):
    login(client)
    reject(client, "as a number", amount="abc")


def test_infinity_and_nan_are_rejected(client):
    """Any one of these would make SUM(amount) on /profile inf or nan for the
    life of the account."""
    login(client)
    for amount in ("inf", "-inf", "nan", "1e400"):
        reject(client, "as a number", amount=amount)


def test_an_amount_over_the_ceiling_is_rejected(client):
    login(client)
    response = reject(client, "no greater than", amount="10000001")
    # The same message /expenses/add gives, naming the limit in rupees.
    assert "₹1,00,00,000" in response.get_data(as_text=True)


def test_a_category_outside_the_list_is_rejected(client):
    """The <select> offered seven values; a POST can name anything at all."""
    login(client)
    reject(client, "from the list", category="Bribes")


def test_a_sql_shaped_category_is_rejected(client):
    login(client)
    reject(client, "from the list", category="Food'; DROP TABLE expenses; --")
    # Still queryable, so the table survived.
    assert expense_count() == SEEDED_COUNT


def test_an_impossible_date_is_rejected(client):
    login(client)
    reject(client, "YYYY-MM-DD", day="2026-13-45")


def test_a_worded_date_is_rejected(client):
    login(client)
    reject(client, "YYYY-MM-DD", day="tomorrow")


def test_a_quoted_date_is_rejected(client):
    login(client)
    reject(client, "YYYY-MM-DD", day="2026-07-01' OR '1'='1")


def test_a_future_date_is_rejected(client):
    login(client)
    day = (date.today() + timedelta(days=1)).isoformat()
    reject(client, "in the future", day=day)


def test_an_over_long_description_is_rejected(client):
    login(client)
    reject(client, "under 200 characters", description="x" * 201)


def test_a_description_at_the_cap_is_accepted(client):
    login(client)
    assert_redirects_to_profile(edit(client, description="x" * 200))
    assert row(1)["description"] == "x" * 200


# ------------------------------------------------------------------ #
# Injection and rendering                                             #
# ------------------------------------------------------------------ #

def test_a_sql_shaped_description_is_stored_verbatim(client):
    """Parameterised, so this is text and only ever text."""
    login(client)
    payload = "'); DROP TABLE expenses; --"
    assert_redirects_to_profile(edit(client, description=payload))

    assert row(1)["description"] == payload
    assert expense_count() == SEEDED_COUNT
    assert client.get("/profile").status_code == 200


def test_a_script_shaped_description_is_escaped_in_the_list(client):
    """The list is where a visitor's free text is rendered for the first time."""
    login(client)
    edit(client, description="<script>alert(1)</script>")

    body = client.get("/profile").get_data(as_text=True)
    assert "<script>alert(1)</script>" not in body
    assert "&lt;script&gt;" in body


# ------------------------------------------------------------------ #
# The expense list                                                    #
# ------------------------------------------------------------------ #

def test_the_list_shows_every_expense(client):
    login(client)
    body = client.get("/profile").get_data(as_text=True)
    assert body.count('class="profile-expense-row"') == SEEDED_COUNT


def test_a_null_description_renders_a_dash(client):
    login(client)
    edit(client, id=1, description="")

    body = client.get("/profile").get_data(as_text=True)
    assert "None" not in body
    assert "—" in body


def test_the_list_is_scoped_to_the_account(client):
    """Somebody else's expense must not appear on this page at all."""
    id = other_accounts_expense(client)
    body = client.get("/profile").get_data(as_text=True)

    assert f'href="/expenses/{id}/edit"' not in body
    assert "Asha&#39;s water bill" not in body


def test_the_list_obeys_the_date_filter(client):
    """The list and the tiles must never disagree about what is in scope."""
    login(client)
    day = (date.today() - timedelta(days=400)).isoformat()
    edit(client, id=1, day=day, description="Long ago")

    inside = client.get(f"/profile?start={day}&end={day}").get_data(as_text=True)
    assert inside.count('class="profile-expense-row"') == 1
    assert "Long ago" in inside

    outside = client.get(f"/profile?start={TODAY}&end={TODAY}").get_data(as_text=True)
    assert "Long ago" not in outside


def test_neither_empty_state_shows_the_list(client):
    login(client)
    filtered = client.get("/profile?start=2000-01-01&end=2000-01-02").get_data(
        as_text=True
    )
    assert "No expenses in this range" in filtered
    assert 'class="profile-expense-row"' not in filtered

    # Logged out first: /register turns a signed-in visitor away, so registering
    # from here would silently do nothing and leave the demo account in place.
    client.get("/logout")
    register(client, "Asha Rao", "asha@spendly.com")
    login(client, email="asha@spendly.com", password="a-good-password")
    fresh = client.get("/profile").get_data(as_text=True)
    assert "No expenses yet" in fresh
    assert 'class="profile-expense-row"' not in fresh


# ------------------------------------------------------------------ #
# No regressions                                                      #
# ------------------------------------------------------------------ #

def test_the_earlier_notices_still_render(client):
    login(client)
    body = client.get("/profile?updated=1&password=1&added=1").get_data(as_text=True)

    assert "Your profile has been updated." in body
    assert "Your password has been changed." in body
    assert "Your expense has been added." in body


def test_the_add_route_is_unchanged(client):
    login(client)
    response = client.post(
        "/expenses/add",
        data={"amount": "250", "category": "Food", "date": TODAY,
              "description": "Lunch"},
    )
    assert_redirects_to_profile(response)
    assert expense_count() == SEEDED_COUNT + 1


def test_the_delete_placeholder_is_untouched(client):
    login(client)
    assert b"coming in Step 9" in client.get("/expenses/1/delete").data
