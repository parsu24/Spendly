"""Tests for the Step 7 add-expense route.

Covers GET/POST /expenses/add: the access control it shares with the account
routes, the validation it applies to every field, and the row it writes. This is
the first route in the project that creates user-authored data, so most of the
file is about what must *not* reach the table — a form that renders its error
correctly but inserts the row anyway is the failure these tests exist to catch.

Every rejection case therefore asserts on the database as well as the response.
"""

from datetime import date, datetime, timedelta, timezone

import pytest

from app import app
from database import db


@pytest.fixture
def client(tmp_path, monkeypatch):
    """A test client whose database is a throwaway file with the demo account.

    Same trick as test_account.py: app.py binds get_db by reference at import
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
    """POST the login form."""
    return client.post("/login", data={"email": email, "password": password})


def register(client, name, email, password="a-good-password"):
    """Create a second account, so a test has someone else's rows to protect."""
    return client.post(
        "/register", data={"name": name, "email": email, "password": password}
    )


def add(client, amount="250", category="Food", day=None, description="Lunch", **extra):
    """POST the add-expense form. `extra` appends fields the form never renders."""
    data = {
        "amount": amount,
        "category": category,
        "date": TODAY if day is None else day,
        "description": description,
    }
    data.update(extra)
    return client.post("/expenses/add", data=data)


def expense_count(user_id=DEMO_ID):
    """How many expenses that account owns.

    Asserting on the response alone cannot tell a rejected write from a silently
    successful one, so every mutation test checks the table itself.
    """
    conn = db.get_db()
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM expenses WHERE user_id = ?", (user_id,)
        ).fetchone()[0]
    finally:
        conn.close()


def latest_expense():
    """The most recently inserted row, whoever owns it."""
    conn = db.get_db()
    try:
        return conn.execute(
            "SELECT * FROM expenses ORDER BY id DESC LIMIT 1"
        ).fetchone()
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


def assert_rejected(response, message):
    """A rejection re-renders the form, says why, and writes nothing."""
    assert response.status_code == 200
    assert message in response.get_data(as_text=True)
    assert expense_count() == SEEDED_COUNT


# ------------------------------------------------------------------ #
# Access control                                                      #
# ------------------------------------------------------------------ #

def test_get_requires_login(client):
    assert_redirects_to_login(client.get("/expenses/add"))


def test_post_requires_login(client):
    """The guard must run before any form parsing — anything can POST here."""
    assert_redirects_to_login(add(client))
    assert expense_count() == SEEDED_COUNT


def test_a_stale_session_clears_itself(client):
    """A cookie pointing at a user the rebuilt database no longer has. Without
    the check this covers, the INSERT would violate the foreign key and 500."""
    with client.session_transaction() as sess:
        sess["user_id"] = 999
        sess["name"] = "Ghost"

    assert_redirects_to_login(client.get("/expenses/add"))
    with client.session_transaction() as sess:
        assert "user_id" not in sess


def test_a_stale_session_cannot_insert(client):
    with client.session_transaction() as sess:
        sess["user_id"] = 999

    assert_redirects_to_login(add(client))
    assert latest_expense()["user_id"] == DEMO_ID


# ------------------------------------------------------------------ #
# The form                                                            #
# ------------------------------------------------------------------ #

def test_the_profile_links_to_the_add_form(client):
    login(client)
    assert 'href="/expenses/add"' in client.get("/profile").get_data(as_text=True)


def test_the_form_offers_every_category_and_nothing_else(client):
    """The dropdown is looped from CATEGORIES, so the two cannot drift apart."""
    login(client)
    body = client.get("/expenses/add").get_data(as_text=True)

    for category in db.CATEGORIES:
        assert f'value="{category}"' in body

    # Seven real options plus the disabled placeholder, and nothing invented.
    assert body.count("<option value=") == len(db.CATEGORIES) + 1


def test_the_form_defaults_the_date_to_today(client):
    login(client)
    body = client.get("/expenses/add").get_data(as_text=True)
    assert f'value="{TODAY}"' in body


def test_the_form_prefills_nothing_else(client):
    login(client)
    body = client.get("/expenses/add").get_data(as_text=True)
    assert 'value=""' in body           # the placeholder option
    assert 'value="250"' not in body    # the amount is never a guess


def test_the_form_carries_no_hidden_owner(client):
    """The account this row belongs to comes from the session, not the page."""
    login(client)
    assert 'type="hidden"' not in client.get("/expenses/add").get_data(as_text=True)


def test_the_form_has_no_dollar_signs(client):
    login(client)
    body = client.get("/expenses/add").get_data(as_text=True)
    assert "$" not in body
    assert "USD" not in body


# ------------------------------------------------------------------ #
# Inserting                                                           #
# ------------------------------------------------------------------ #

def test_a_valid_expense_is_inserted(client):
    login(client)
    assert_redirects_to_profile(add(client, amount="250", category="Food"))

    assert expense_count() == SEEDED_COUNT + 1
    row = latest_expense()
    assert row["user_id"] == DEMO_ID
    assert row["amount"] == 250.0
    assert row["category"] == "Food"
    assert row["date"] == TODAY
    assert row["description"] == "Lunch"


def test_a_successful_add_confirms_itself(client):
    login(client)
    response = add(client)
    assert "added=1" in response.headers["Location"]

    body = client.get(response.headers["Location"]).get_data(as_text=True)
    assert "Your expense has been added." in body


def test_the_totals_move(client):
    """The figures on /profile are the real proof the row landed."""
    login(client)
    body = client.get("/profile").get_data(as_text=True)
    assert "₹18,240" in body

    add(client, amount="250")
    body = client.get("/profile").get_data(as_text=True)
    assert "₹18,490" in body
    # The "Expenses recorded" tile, which renders the bare count.
    assert ">9</span>" in body


def test_a_blank_description_is_stored_as_null(client):
    """The column is the one nullable field; a blank note is its absence."""
    login(client)
    assert_redirects_to_profile(add(client, description=""))
    assert latest_expense()["description"] is None


def test_a_whitespace_description_is_stored_as_null(client):
    login(client)
    add(client, description="   ")
    assert latest_expense()["description"] is None


def test_a_decimal_amount_is_stored(client):
    login(client)
    add(client, amount="99.50")
    assert latest_expense()["amount"] == 99.5


def test_an_over_precise_amount_is_rounded(client):
    """amount is REAL; storing unrounded input makes the totals drift."""
    login(client)
    add(client, amount="99.999")
    assert latest_expense()["amount"] == 100.0


def test_a_past_date_is_accepted(client):
    login(client)
    day = (date.today() - timedelta(days=40)).isoformat()
    assert_redirects_to_profile(add(client, day=day))
    assert latest_expense()["date"] == day


def test_created_at_comes_from_the_column_default(client):
    """datetime('now') is UTC and includes a time; a route-supplied date.today()
    would be local and ten characters long."""
    login(client)
    add(client)
    stamp = latest_expense()["created_at"]

    assert len(stamp) == 19          # 'YYYY-MM-DD HH:MM:SS', not a bare date
    assert stamp.startswith(datetime.now(timezone.utc).date().isoformat())


def test_an_amount_just_under_the_ceiling_is_accepted(client):
    """The limit is a typo guard, not a cap on what may be recorded."""
    login(client)
    assert_redirects_to_profile(add(client, amount="9999999"))
    assert latest_expense()["amount"] == 9999999.0


# ------------------------------------------------------------------ #
# Rejections — missing fields                                         #
# ------------------------------------------------------------------ #

MISSING = "Please fill in every field."


def test_a_blank_amount_is_rejected(client):
    login(client)
    assert_rejected(add(client, amount=""), MISSING)


def test_a_blank_category_is_rejected(client):
    login(client)
    assert_rejected(add(client, category=""), MISSING)


def test_a_blank_date_is_rejected(client):
    login(client)
    assert_rejected(add(client, day=""), MISSING)


def test_a_rejection_keeps_the_other_fields(client):
    """Fixing one field must not mean retyping the other three."""
    login(client)
    body = add(client, amount="", category="Bills", description="Water bill").get_data(
        as_text=True
    )

    assert 'value="Bills" selected' in body
    assert 'value="Water bill"' in body
    assert f'value="{TODAY}"' in body


# ------------------------------------------------------------------ #
# Rejections — the amount                                             #
# ------------------------------------------------------------------ #

def test_zero_is_rejected(client):
    login(client)
    assert_rejected(add(client, amount="0"), "greater than zero")


def test_a_negative_amount_is_rejected(client):
    login(client)
    assert_rejected(add(client, amount="-50"), "greater than zero")


def test_a_non_numeric_amount_is_rejected(client):
    login(client)
    assert_rejected(add(client, amount="abc"), "as a number")


def test_a_comma_grouped_amount_is_rejected(client):
    """float() cannot read '1,200' — better refused than silently misread."""
    login(client)
    assert_rejected(add(client, amount="1,200"), "as a number")


def test_infinity_and_nan_are_rejected(client):
    """float() accepts all three of these happily, and any one of them would
    make SUM(amount) on /profile inf or nan for the life of the account."""
    login(client)
    for amount in ("inf", "-inf", "nan", "1e400"):
        assert_rejected(add(client, amount=amount), "as a number")


def test_an_amount_over_the_ceiling_is_rejected(client):
    login(client)
    response = add(client, amount="10000001")
    assert_rejected(response, "no greater than")
    # The message names the limit, in rupees and Indian grouping.
    assert "₹1,00,00,000" in response.get_data(as_text=True)


# ------------------------------------------------------------------ #
# Rejections — the category                                           #
# ------------------------------------------------------------------ #

def test_a_category_outside_the_list_is_rejected(client):
    """The <select> offered seven values; a POST can name anything at all."""
    login(client)
    assert_rejected(add(client, category="Bribes"), "from the list")


def test_a_sql_shaped_category_is_rejected(client):
    login(client)
    assert_rejected(add(client, category="Food'; DROP TABLE expenses; --"),
                    "from the list")
    # Still queryable, so the table survived.
    assert expense_count() == SEEDED_COUNT


def test_the_category_is_case_sensitive(client):
    """CATEGORIES holds 'Food'; accepting 'food' would put two spellings of one
    category in the breakdown."""
    login(client)
    assert_rejected(add(client, category="food"), "from the list")


# ------------------------------------------------------------------ #
# Rejections — the date                                               #
# ------------------------------------------------------------------ #

def test_an_impossible_date_is_rejected(client):
    login(client)
    assert_rejected(add(client, day="2026-13-45"), "YYYY-MM-DD")


def test_a_worded_date_is_rejected(client):
    login(client)
    assert_rejected(add(client, day="tomorrow"), "YYYY-MM-DD")


def test_a_quoted_date_is_rejected(client):
    """The injection attempt Step 6 rejects on the filter, on the write side."""
    login(client)
    assert_rejected(add(client, day="2026-07-01' OR '1'='1"), "YYYY-MM-DD")


def test_a_future_date_is_rejected(client):
    login(client)
    day = (date.today() + timedelta(days=1)).isoformat()
    assert_rejected(add(client, day=day), "in the future")


def test_a_rejected_future_date_is_echoed_back(client):
    """It parsed, so the field can hold it — <input type="date"> will only
    display canonical YYYY-MM-DD."""
    login(client)
    day = (date.today() + timedelta(days=1)).isoformat()
    assert f'value="{day}"' in add(client, day=day).get_data(as_text=True)


# ------------------------------------------------------------------ #
# Rejections — the description                                        #
# ------------------------------------------------------------------ #

def test_an_over_long_description_is_rejected(client):
    """Rejected rather than truncated: silently storing the first 200 characters
    would report a note as saved when part of it was thrown away."""
    login(client)
    assert_rejected(add(client, description="x" * 201), "under 200 characters")


def test_a_description_at_the_cap_is_accepted(client):
    login(client)
    assert_redirects_to_profile(add(client, description="x" * 200))
    assert latest_expense()["description"] == "x" * 200


# ------------------------------------------------------------------ #
# Injection and scoping                                               #
# ------------------------------------------------------------------ #

def test_a_sql_shaped_description_is_stored_verbatim(client):
    """Parameterised, so this is text and only ever text."""
    login(client)
    payload = "'); DROP TABLE expenses; --"
    assert_redirects_to_profile(add(client, description=payload))

    assert latest_expense()["description"] == payload
    assert expense_count() == SEEDED_COUNT + 1
    # The table is still there and the page still renders.
    assert client.get("/profile").status_code == 200


def test_the_owner_comes_from_the_session_not_the_form(client):
    """A form that could name its owner is how one account writes rows into
    another's ledger."""
    register(client, "Asha Rao", "asha@spendly.com")
    login(client)

    assert_redirects_to_profile(add(client, user_id=2))

    assert expense_count(DEMO_ID) == SEEDED_COUNT + 1
    assert expense_count(2) == 0
    assert latest_expense()["user_id"] == DEMO_ID


def test_an_id_in_the_form_cannot_reassign_the_row(client):
    """The same attempt against the row's own primary key."""
    login(client)
    add(client, id=1)
    assert expense_count() == SEEDED_COUNT + 1


# ------------------------------------------------------------------ #
# No regressions                                                      #
# ------------------------------------------------------------------ #

def test_the_first_run_empty_state_offers_the_form(client):
    """Registered before logging in — /register turns a signed-in visitor away."""
    register(client, "Asha Rao", "asha@spendly.com")
    login(client, email="asha@spendly.com", password="a-good-password")

    body = client.get("/profile").get_data(as_text=True)
    assert "No expenses yet" in body
    assert 'href="/expenses/add"' in body


def test_an_account_can_add_its_first_expense(client):
    register(client, "Asha Rao", "asha@spendly.com")
    login(client, email="asha@spendly.com", password="a-good-password")

    add(client, amount="500", category="Bills")
    body = client.get("/profile").get_data(as_text=True)

    assert "No expenses yet" not in body
    assert "₹500" in body


def test_the_step_five_notices_still_render(client):
    login(client)
    body = client.get("/profile?updated=1&password=1").get_data(as_text=True)
    assert "Your profile has been updated." in body
    assert "Your password has been changed." in body


def test_the_step_six_filter_still_scopes_the_new_row(client):
    """A row dated inside the window counts; the same row outside it does not."""
    login(client)
    day = (date.today() - timedelta(days=40)).isoformat()
    add(client, amount="777", category="Health", day=day)

    inside = client.get(f"/profile?start={day}&end={day}").get_data(as_text=True)
    assert "₹777" in inside

    outside = client.get(f"/profile?start={TODAY}&end={TODAY}").get_data(as_text=True)
    assert "₹777" not in outside
