"""Tests for the Step 6 date filter on the profile page.

Covers the two query parameters `/profile` and `/profile/<id>` learned to read:
how `?start=` / `?end=` are parsed, which expenses they select, and what the
page says when they select nothing or cannot be used at all.

The failures this file exists to catch are the ones a rendered page hides.
A filter that quietly drops a boundary row, one that reports "No expenses yet"
to an account holding eighteen thousand rupees because the window was last
February, one that half-applies a rejected range and shows figures for a
window nobody asked for, and one that reaches a value from the address bar
into SQL as text rather than as a bound parameter — all four render a page
that looks fine. So the expected figures here are computed a second time in
Python from the rows themselves, the range note is read as the statement of
what is in force, and the ownership check is re-tested with a range attached.

There is a fifth failure worth naming, because it is the one an incomplete
suite misses: a filter that was never wired up at all. Every seeded expense
falls inside "this month", "this year" and "the last 30 days", so a range
covering any of those produces the all-time figures whether or not the query
was filtered. That is why the tests below pair a count with the range note
naming the window in force, and read the category bars rather than trusting
that a 100% bar somewhere on the page belongs to the range.

seed_db() spreads the demo account's eight expenses across the days of the
*current* month, so every range below is derived from `date.today()` or from
the seeded rows. Nothing is written down that stops being true next month.
"""

import re
from datetime import date, timedelta

import pytest

from app import app
from database import db


@pytest.fixture
def client(tmp_path, monkeypatch):
    """A test client whose database is a throwaway file with the demo account.

    Same trick as test_profile.py: app.py binds get_db by reference at import
    time, but get_db reads the module-level DB_PATH when it is *called*, so
    patching the attribute here redirects the route's reads to the temporary
    file too — no test can damage spendly.db.
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

# Its eight expenses, all dated inside the current month.
SEEDED_COUNT = 8
SEEDED_TOTAL = "₹18,240"
SEEDED_AVERAGE = "₹2,280"      # 18,240 / 8

# Copied from app.py. Written out rather than imported, so a change to either
# message has to be made deliberately in both places.
RANGE_INVALID = "Please enter dates as YYYY-MM-DD."
RANGE_BACKWARDS = "The start date is after the end date."


def login(client, email=DEMO_EMAIL, password=DEMO_PASSWORD):
    """POST the login form."""
    return client.post("/login", data={"email": email, "password": password})


def register(client, name, email, password="a-good-password"):
    """Create a second account, so a test has someone else's rows to miss."""
    return client.post(
        "/register", data={"name": name, "email": email, "password": password}
    )


def profile_text(client, path="/profile", **params):
    """GET a profile URL as text — the rupee symbol is multi-byte."""
    return client.get(path, query_string=params).get_data(as_text=True)


# ------------------------------------------------------------------ #
# Reading the page and the rows                                       #
# ------------------------------------------------------------------ #

def stat(body, label):
    """The value rendered in the stat tile carrying this label.

    Reading the tile rather than searching the whole page is what lets a test
    say "the count is 3" instead of "3 appears somewhere", which a date in the
    filter fields would satisfy on its own.
    """
    after_label = body.split(f'<span class="dash-stat-label">{label}</span>', 1)[1]
    return after_label.split('<span class="dash-stat-value">', 1)[1].split("</span>", 1)[0]


# One category bar: its label, the width of its track, and its amount.
BAR_ROW = re.compile(
    r'<span class="profile-bar-label">(?P<name>[^<]*)</span>.*?'
    r'style="width: (?P<width>[0-9.]+)%".*?'
    r'<span class="profile-bar-value">(?P<value>[^<]*)</span>',
    re.S,
)


def bars(body):
    """Every category bar on the page as (name, width, amount), widest first.

    Read as a list rather than searched for, because "width: 100.0% appears
    somewhere" is true of the unfiltered page too — the question a filtered
    page has to answer is which category is widest and what it is worth.
    """
    return [
        (match["name"], float(match["width"]), match["value"])
        for match in BAR_ROW.finditer(body)
    ]


def seeded_rows():
    """Every expense the demo account owns, read straight from the database."""
    conn = db.get_db()
    try:
        return [
            (row["date"], row["amount"], row["category"])
            for row in conn.execute(
                "SELECT date, amount, category FROM expenses"
                "  WHERE user_id = ? ORDER BY date",
                (DEMO_ID,),
            )
        ]
    finally:
        conn.close()


def seeded_days():
    """The distinct seeded dates, oldest first."""
    return sorted({date.fromisoformat(day) for day, _, _ in seeded_rows()})


def half_window():
    """A window over the older half of the seeded month.

    Wide enough to hold several expenses and narrow enough to leave several
    out, so the bars it draws are demonstrably not the all-time bars.
    """
    days = seeded_days()
    return days[0], days[len(days) // 2]


def expense_count(user_id=DEMO_ID):
    """How many expenses that account owns, whatever any page claims."""
    conn = db.get_db()
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM expenses WHERE user_id = ?", (user_id,)
        ).fetchone()[0]
    finally:
        conn.close()


def expected(start=None, end=None):
    """(count, total) for a range, filtered in Python instead of in SQL.

    A second implementation on purpose. A BETWEEN that lost a boundary row
    would still agree with itself, so the figures a range produces are checked
    against a comparison written the other way round rather than against the
    route's own arithmetic.
    """
    rows = rows_in(start, end)
    return len(rows), sum(amount for _, amount, _ in rows)


def rows_in(start=None, end=None):
    """The seeded rows a range covers, both bounds inclusive."""
    return [
        row
        for row in seeded_rows()
        if (start is None or row[0] >= start.isoformat())
        and (end is None or row[0] <= end.isoformat())
    ]


def expected_breakdown(start=None, end=None):
    """[(category, total)] for a range, largest first, computed in Python."""
    totals = {}
    for _, amount, category in rows_in(start, end):
        totals[category] = totals.get(category, 0) + amount
    return sorted(totals.items(), key=lambda item: -item[1])


def assert_figures(body, count, total):
    """The two tiles that carry the range's answer."""
    assert stat(body, "Expenses recorded") == str(count)
    assert stat(body, "Total spent") == db.format_inr(total)


def assert_all_time(body):
    """The Step 4 figures, and a page that says that is what they are."""
    assert stat(body, "Expenses recorded") == str(SEEDED_COUNT)
    assert stat(body, "Total spent") == SEEDED_TOTAL
    assert "Showing all time" in body


def spoken(day):
    """The page's wording for a bound: 1 Jul 2026, never zero-padded."""
    return f"{day.day} {day.strftime('%b %Y')}"


def last_month():
    """A window wholly inside last month, where the seed never puts anything."""
    last_day = date.today().replace(day=1) - timedelta(days=1)
    return last_day.replace(day=1), last_day


def backwards():
    """A pair the wrong way round: tomorrow to today.

    Built by stepping a day rather than from the calendar month, because on
    the 1st "today back to the 1st" is one day, not a backwards range.
    """
    today = date.today()
    return today + timedelta(days=1), today


# Werkzeug has returned both relative and absolute Location headers across
# versions; every redirect assertion here tolerates either.
def assert_redirects_to_login(response):
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


# ------------------------------------------------------------------ #
# Access control — a range is not a way in                            #
# ------------------------------------------------------------------ #

def test_a_filtered_url_still_requires_login(client):
    """The guard runs before request.args is read, so a range cannot skip it."""
    first, last = seeded_days()[0], seeded_days()[-1]
    response = client.get(
        "/profile", query_string={"start": first.isoformat(), "end": last.isoformat()}
    )
    assert_redirects_to_login(response)


# Deliberately no "the logged-out refusal leaks nothing" test here. The 302 a
# guard returns is a Werkzeug stub that has never carried the account in any
# step, so an assertion against it cannot fail and would only look like cover.
# test_profile.py::test_logged_out_profile_leaks_nothing already documents it
# once, and the guard itself is tested above.


def test_a_stale_session_is_cleared_on_a_filtered_url(client):
    """A cookie pointing at a user the rebuilt database no longer has."""
    with client.session_transaction() as sess:
        sess["user_id"] = 999
        sess["name"] = "Ghost"

    response = client.get("/profile", query_string={"start": "2026-01-01"})
    assert_redirects_to_login(response)
    with client.session_transaction() as sess:
        assert "user_id" not in sess


def test_the_dynamic_route_takes_a_range_for_your_own_id(client):
    login(client)
    start, end = half_window()
    params = {"start": start.isoformat(), "end": end.isoformat()}

    response = client.get(f"/profile/{DEMO_ID}", query_string=params)
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert f"Showing {spoken(start)} to {spoken(end)}" in body
    assert body == profile_text(client, **params)


def test_the_dynamic_route_still_refuses_another_id_with_a_range(client):
    """A filter is not a reason to relax ownership."""
    register(client, "Asha Rao", "asha@spendly.com")
    login(client)

    response = client.get(
        f"/profile/{DEMO_ID + 1}", query_string={"start": date.today().isoformat()}
    )
    assert response.status_code == 404


def test_the_ownership_check_runs_before_the_range_is_parsed(client):
    """An unusable range must not turn somebody else's 404 into an error page."""
    register(client, "Asha Rao", "asha@spendly.com")
    login(client)

    response = client.get(
        f"/profile/{DEMO_ID + 1}", query_string={"start": "not-a-date"}
    )
    assert response.status_code == 404
    assert RANGE_INVALID not in response.get_data(as_text=True)


def test_a_range_never_widens_the_result_past_your_own_rows(client):
    """The window narrows a set that is already yours; it cannot reach further."""
    register(client, "Asha Rao", "asha@spendly.com")

    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO expenses (user_id, amount, category, date, description)"
            " VALUES (?, ?, ?, ?, ?)",
            (DEMO_ID + 1, 5000.0, "Food", date.today().isoformat(), "Asha's lunch"),
        )
        conn.commit()
    finally:
        conn.close()

    login(client)
    today = date.today()
    first = today.replace(day=1)
    body = profile_text(client, start=first.isoformat(), end=today.isoformat())

    # Dated inside the window and in the largest category, so a query that
    # dropped `WHERE user_id = ?` when it gained a BETWEEN would show nine
    # expenses, ₹23,240, and a Food bar worth ₹11,630.
    assert f"Showing {spoken(first)} to {spoken(today)}" in body
    assert_figures(body, SEEDED_COUNT, 18240.0)
    assert bars(body)[0] == ("Food", 100.0, "₹6,630")


# ------------------------------------------------------------------ #
# The unfiltered page — Step 4, unchanged                             #
# ------------------------------------------------------------------ #

def test_no_query_string_is_the_step_4_page(client):
    login(client)
    body = profile_text(client)
    assert_all_time(body)
    assert stat(body, "Top category") == "Food"


def test_every_category_bar_is_still_present(client):
    login(client)
    drawn = bars(profile_text(client))

    assert [name for name, _, _ in drawn] == [
        category for category, _ in expected_breakdown()
    ]
    assert drawn[0] == ("Food", 100.0, "₹6,630")


def test_blank_bounds_are_the_unfiltered_page(client):
    """Blank means unbounded, not "a range of nothing"."""
    login(client)
    body = profile_text(client, start="", end="")

    assert_all_time(body)
    assert RANGE_INVALID not in body


def test_no_range_offers_no_clear_link(client):
    """Nothing to clear, so the control that clears it stays off the page."""
    login(client)
    assert ">Clear<" not in profile_text(client)


def test_the_fields_start_empty(client):
    login(client)
    body = profile_text(client)
    assert 'name="start" value=""' in body
    assert 'name="end" value=""' in body


def test_the_updated_notice_survives_a_range(client):
    """Step 5's ?updated=1 shares the query string this step now also reads."""
    login(client)
    today = date.today()
    first = today.replace(day=1)
    body = profile_text(
        client, updated=1, start=first.isoformat(), end=today.isoformat()
    )

    assert "Your profile has been updated." in body
    assert f"Showing {spoken(first)} to {spoken(today)}" in body


def test_the_password_notice_survives_a_range(client):
    """Its own block in the template, not an elif — so it needs its own test."""
    login(client)
    today = date.today()
    first = today.replace(day=1)
    body = profile_text(
        client, password=1, start=first.isoformat(), end=today.isoformat()
    )

    assert "Your password has been changed." in body
    assert f"Showing {spoken(first)} to {spoken(today)}" in body


# ------------------------------------------------------------------ #
# The filter bar                                                      #
# ------------------------------------------------------------------ #

def test_the_filter_bar_is_a_get_form_to_profile(client):
    """GET, so the range lives in the URL and a filtered view is bookmarkable."""
    login(client)
    body = profile_text(client)

    assert '<form class="profile-filter" method="get" action="/profile">' in body
    assert 'type="date" id="start" name="start"' in body
    assert 'type="date" id="end" name="end"' in body
    assert ">Apply</button>" in body


def test_the_this_month_preset_runs_from_the_first_to_today(client):
    login(client)
    today = date.today()
    href = f"/profile?start={today.replace(day=1).isoformat()}&amp;end={today.isoformat()}"
    assert f'<a href="{href}">This month</a>' in profile_text(client)


def test_the_last_30_days_preset_is_inclusive_at_both_ends(client):
    """29 days back plus today is 30 days of spending, not 31."""
    login(client)
    today = date.today()
    start = (today - timedelta(days=29)).isoformat()
    href = f"/profile?start={start}&amp;end={today.isoformat()}"
    assert f'<a href="{href}">Last 30 days</a>' in profile_text(client)


def test_the_this_year_preset_starts_on_1_january(client):
    login(client)
    today = date.today()
    href = f"/profile?start={today.replace(month=1, day=1).isoformat()}&amp;end={today.isoformat()}"
    assert f'<a href="{href}">This year</a>' in profile_text(client)


def test_all_time_is_a_bare_profile_link(client):
    """No parameters at all — the same address the Clear control goes to."""
    login(client)
    assert '<a href="/profile">All time</a>' in profile_text(client)


def test_a_range_in_force_offers_a_clear_link(client):
    login(client)
    start, end = last_month()
    body = profile_text(client, start=start.isoformat(), end=end.isoformat())
    assert '<a class="btn-ghost" href="/profile">Clear</a>' in body


def test_applying_twice_is_idempotent(client):
    """The fields come back holding the range, so Apply again means the same."""
    login(client)
    first, last = seeded_days()[0], seeded_days()[-1]
    body = profile_text(client, start=first.isoformat(), end=last.isoformat())

    assert f'name="start" value="{first.isoformat()}"' in body
    assert f'name="end" value="{last.isoformat()}"' in body


def test_a_bound_is_re_serialised_before_it_is_echoed(client):
    """What goes back into the field is canonical ISO, not the raw submission —
    <input type="date"> displays nothing else."""
    login(client)
    day = seeded_days()[0]
    body = profile_text(client, start=f"  {day.isoformat()}  ")
    assert f'name="start" value="{day.isoformat()}"' in body


def test_the_filter_bar_renders_on_an_empty_range(client):
    """The way out of a window that found nothing has to be on that page."""
    start, end = last_month()
    login(client)
    body = profile_text(client, start=start.isoformat(), end=end.isoformat())

    assert "No expenses in this range" in body       # the state under test
    assert '<form class="profile-filter" method="get"' in body


def test_the_filter_bar_renders_for_an_account_with_no_expenses(client):
    """Registered before signing in — /register turns a signed-in visitor away."""
    register(client, "Asha Rao", "asha@spendly.com")
    login(client, email="asha@spendly.com", password="a-good-password")

    body = profile_text(client)
    assert '<form class="profile-filter" method="get"' in body
    assert "No expenses yet" in body


# ------------------------------------------------------------------ #
# Ranges that select                                                  #
# ------------------------------------------------------------------ #

# Every seeded expense falls inside each of the three windows below, so the
# count alone cannot tell a working filter from one that was never applied.
# The range note is what separates them: it names the window in force, and it
# says "Showing all time" when none is.

def test_this_month_counts_every_seeded_expense(client):
    """seed_db() spreads all eight across the days of the current month."""
    login(client)
    today = date.today()
    first = today.replace(day=1)
    body = profile_text(client, start=first.isoformat(), end=today.isoformat())

    assert f"Showing {spoken(first)} to {spoken(today)}" in body
    assert_figures(body, SEEDED_COUNT, 18240.0)


def test_this_year_counts_every_seeded_expense(client):
    """The presets have to agree with each other: this month ≤ this year."""
    login(client)
    today = date.today()
    january = today.replace(month=1, day=1)
    body = profile_text(client, start=january.isoformat(), end=today.isoformat())

    assert f"Showing {spoken(january)} to {spoken(today)}" in body
    assert_figures(body, SEEDED_COUNT, 18240.0)


def test_last_30_days_selects_the_expenses_inside_it(client):
    login(client)
    today = date.today()
    start = today - timedelta(days=29)
    body = profile_text(client, start=start.isoformat(), end=today.isoformat())

    assert f"Showing {spoken(start)} to {spoken(today)}" in body
    assert_figures(body, *expected(start, today))


def test_a_narrow_window_selects_only_what_is_inside_it(client):
    login(client)
    start, end = half_window()
    body = profile_text(client, start=start.isoformat(), end=end.isoformat())

    assert f"Showing {spoken(start)} to {spoken(end)}" in body
    assert_figures(body, *expected(start, end))


def test_the_bars_redraw_for_the_range(client):
    """Every bar the range earns, with its own amount, and none it did not."""
    login(client)
    start, end = half_window()
    body = profile_text(client, start=start.isoformat(), end=end.isoformat())

    drawn = bars(body)
    assert [(name, amount) for name, _, amount in drawn] == [
        (category, db.format_inr(total))
        for category, total in expected_breakdown(start, end)
    ]

    # Largest first, the ordering the breakdown query promises.
    widths = [width for _, width, _ in drawn]
    assert widths == sorted(widths, reverse=True)


def test_the_excluded_categories_lose_their_bars(client):
    """A category with nothing inside the window is not drawn at ₹0."""
    login(client)
    start, end = half_window()
    body = profile_text(client, start=start.isoformat(), end=end.isoformat())

    inside = {category for category, _ in expected_breakdown(start, end)}
    for category, _ in expected_breakdown():
        if category not in inside:
            assert f'<span class="profile-bar-label">{category}</span>' not in body


def test_the_widest_bar_is_recomputed_for_the_range(client):
    """largest comes from the filtered breakdown, so the range's own top
    category fills the track. Measured against the all-time largest it would
    render short — and "a 100% bar is on the page" would not notice, because
    the unfiltered page has one too."""
    login(client)
    start, end = half_window()
    body = profile_text(client, start=start.isoformat(), end=end.isoformat())

    top_category, top_total = expected_breakdown(start, end)[0]
    assert bars(body)[0] == (top_category, 100.0, db.format_inr(top_total))
    assert stat(body, "Top category") == top_category


def test_an_expense_dated_on_the_start_bound_is_included(client):
    """BETWEEN is inclusive at the lower end and that is the intent: opening
    the window on the oldest expense still counts it."""
    login(client)
    day = seeded_days()[0]
    body = profile_text(client, start=day.isoformat())

    assert f"Showing everything from {spoken(day)}" in body
    assert_figures(body, *expected(start=day))
    assert stat(body, "Expenses recorded") == str(SEEDED_COUNT)


def test_an_expense_dated_on_the_end_bound_is_included(client):
    """BETWEEN is inclusive at the upper end too."""
    login(client)
    day = seeded_days()[-1]
    body = profile_text(client, end=day.isoformat())

    assert f"Showing everything up to {spoken(day)}" in body
    assert_figures(body, *expected(end=day))
    assert stat(body, "Expenses recorded") == str(SEEDED_COUNT)


def test_a_day_before_the_start_bound_is_excluded(client):
    login(client)
    day = seeded_days()[0] + timedelta(days=1)
    body = profile_text(client, start=day.isoformat())

    assert f"Showing everything from {spoken(day)}" in body
    assert_figures(body, *expected(start=day))


def test_a_start_alone_leaves_the_upper_end_open(client):
    login(client)
    day = seeded_days()[-1]
    body = profile_text(client, start=day.isoformat())

    assert_figures(body, *expected(start=day))
    assert f"Showing everything from {spoken(day)}" in body


def test_an_end_alone_leaves_the_lower_end_open(client):
    login(client)
    day = seeded_days()[0]
    body = profile_text(client, end=day.isoformat())

    assert_figures(body, *expected(end=day))
    assert f"Showing everything up to {spoken(day)}" in body


def test_the_range_note_states_the_window_in_words(client):
    """Spoken, not ISO, and not zero-padded — '01 Jul 2026' reads like a
    filename."""
    login(client)
    today = date.today()
    first = today.replace(day=1)
    body = profile_text(client, start=first.isoformat(), end=today.isoformat())

    assert f"Showing {spoken(first)} to {spoken(today)}" in body
    assert "Showing 01 " not in body


def test_clearing_the_range_restores_the_full_totals(client):
    """All time is a link back to a bare /profile, not a fourth kind of range."""
    login(client)
    start, end = last_month()

    # Asserted first, so "cleared" means something was in force to clear.
    filtered = profile_text(client, start=start.isoformat(), end=end.isoformat())
    assert_figures(filtered, 0, 0)

    assert_all_time(profile_text(client))


# ------------------------------------------------------------------ #
# An empty range is not an empty account                              #
# ------------------------------------------------------------------ #

def test_an_empty_range_says_it_is_the_range_that_is_empty(client):
    """The single most likely bug in this step: telling someone with eighteen
    thousand rupees of history that they have no expenses yet."""
    login(client)
    start, end = last_month()
    body = profile_text(client, start=start.isoformat(), end=end.isoformat())

    assert "No expenses in this range" in body
    assert "No expenses yet" not in body


def test_an_empty_range_offers_the_way_back(client):
    login(client)
    start, end = last_month()
    body = profile_text(client, start=start.isoformat(), end=end.isoformat())
    assert '<a href="/profile">show all time</a>' in body


def test_an_empty_range_still_renders_the_tiles(client):
    """Zero is a real answer once a window has been chosen; hiding the tiles
    would make the page look broken rather than empty."""
    login(client)
    start, end = last_month()
    body = profile_text(client, start=start.isoformat(), end=end.isoformat())

    assert_figures(body, 0, 0)
    assert stat(body, "Top category") == "—"


def test_an_empty_range_shows_none_of_the_history_it_excluded(client):
    login(client)
    start, end = last_month()
    body = profile_text(client, start=start.isoformat(), end=end.isoformat())

    assert SEEDED_TOTAL not in body
    assert "Where your money goes" not in body


def test_an_empty_account_still_says_no_expenses_yet(client):
    """No range in force, so the wording is about the account, not the window."""
    register(client, "Asha Rao", "asha@spendly.com")
    login(client, email="asha@spendly.com", password="a-good-password")

    body = profile_text(client)
    assert "No expenses yet" in body
    assert "No expenses in this range" not in body
    assert SEEDED_TOTAL not in body


# ------------------------------------------------------------------ #
# The average tile                                                    #
# ------------------------------------------------------------------ #

def test_the_this_month_tile_is_gone(client):
    """Replaced, not added beside: a tile hard-wired to the calendar month
    contradicts the three next to it once any window can be chosen. "This
    month" survives on the page as a preset link only."""
    login(client)
    body = profile_text(client)

    assert '<span class="dash-stat-label">Average per expense</span>' in body
    assert '<span class="dash-stat-label">This month</span>' not in body


def test_the_average_is_the_total_over_the_count(client):
    login(client)
    body = profile_text(client)

    assert stat(body, "Average per expense") == SEEDED_AVERAGE
    assert stat(body, "Total spent") == SEEDED_TOTAL
    assert stat(body, "Expenses recorded") == str(SEEDED_COUNT)


def test_the_average_is_recomputed_for_the_range(client):
    """It divides the figures on screen, not the all-time pair behind them."""
    login(client)
    start, end = half_window()
    body = profile_text(client, start=start.isoformat(), end=end.isoformat())

    count, total = expected(start, end)
    assert f"Showing {spoken(start)} to {spoken(end)}" in body
    assert stat(body, "Average per expense") == db.format_inr(total / count)


def test_an_empty_range_averages_to_zero_rather_than_dividing_by_it(client):
    login(client)
    start, end = last_month()
    body = profile_text(client, start=start.isoformat(), end=end.isoformat())
    assert stat(body, "Average per expense") == "₹0"


# ------------------------------------------------------------------ #
# Ranges that are refused                                             #
# ------------------------------------------------------------------ #

def test_an_unparseable_date_falls_back_to_all_time(client):
    """No traceback, no 500, and no half-applied window."""
    login(client)
    response = client.get(
        "/profile", query_string={"start": "2026-13-45", "end": "x"}
    )
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert RANGE_INVALID in body
    assert_all_time(body)


def test_a_rejected_range_keeps_what_was_typed_beside_the_error(client):
    """A corrected typo must not mean retyping both fields."""
    login(client)
    body = profile_text(client, start="2026-13-45", end="x")

    assert RANGE_INVALID in body
    assert 'name="start" value="2026-13-45"' in body
    assert 'name="end" value="x"' in body


def test_one_bad_bound_discards_the_good_one_with_it(client):
    """"Ignore the whole filter" is the rule, both ways round. An
    implementation that kept the bound it could parse would report a window
    nobody asked for — and would pass every both-sides-invalid test."""
    login(client)
    good = seeded_days()[len(seeded_days()) // 2]

    for params in (
        {"start": good.isoformat(), "end": "x"},
        {"start": "x", "end": good.isoformat()},
    ):
        body = profile_text(client, **params)
        assert RANGE_INVALID in body
        assert_all_time(body)
        assert f"Showing everything from {spoken(good)}" not in body
        assert f"Showing everything up to {spoken(good)}" not in body


def test_a_rejected_range_does_not_claim_a_window_is_in_force(client):
    """The figures are all-time, so the page must not offer a Clear control or
    a note naming dates it did not apply."""
    login(client)
    body = profile_text(client, start="2026-13-45", end="x")

    assert RANGE_INVALID in body
    assert "Showing all time" in body
    assert ">Clear<" not in body


def test_a_backwards_range_is_reported_specifically(client):
    login(client)
    start, end = backwards()
    body = profile_text(client, start=start.isoformat(), end=end.isoformat())

    assert RANGE_BACKWARDS in body
    assert RANGE_INVALID not in body


def test_a_backwards_range_is_not_silently_swapped(client):
    """Swapping would teach the visitor that a range typed backwards worked.
    The note is what gives it away — a swap would name the corrected window."""
    login(client)
    start, end = backwards()
    body = profile_text(client, start=start.isoformat(), end=end.isoformat())

    assert RANGE_BACKWARDS in body
    assert "Showing all time" in body
    assert f"Showing {spoken(end)} to {spoken(start)}" not in body


def test_a_backwards_range_shows_figures_rather_than_an_empty_result(client):
    """start > end selects nothing in SQL, so a route that ran the query anyway
    would render the empty state instead of reporting the mistake."""
    login(client)
    start, end = backwards()
    body = profile_text(client, start=start.isoformat(), end=end.isoformat())

    assert RANGE_BACKWARDS in body
    assert_figures(body, SEEDED_COUNT, 18240.0)
    assert "No expenses in this range" not in body


def test_an_injection_payload_is_rejected_as_a_date(client):
    """A quoted payload in a bound parameter. fromisoformat refuses it, so it
    never reaches the query at all — the parse is the defence, and the binding
    is the reason a value that slipped through would still be inert."""
    login(client)
    body = profile_text(client, start="2026-07-01' OR '1'='1")

    assert RANGE_INVALID in body
    assert_all_time(body)


def test_an_injection_payload_changes_nothing_in_the_database(client):
    login(client)
    profile_text(client, start="2026-07-01' OR '1'='1", end="1'; DROP TABLE expenses;--")

    assert expense_count() == SEEDED_COUNT
    conn = db.get_db()
    try:
        assert conn.execute(
            "SELECT COUNT(*) FROM users"
        ).fetchone()[0] == 1
    finally:
        conn.close()


def test_an_echoed_payload_is_escaped_out_of_the_attribute(client):
    """It comes back into the field it was typed into, so the quotes it carries
    must not be able to close that attribute."""
    login(client)
    body = profile_text(client, start="2026-07-01' OR '1'='1")

    assert "value=\"2026-07-01' OR" not in body
    assert 'value="2026-07-01&#39; OR &#39;1&#39;=&#39;1"' in body


# ------------------------------------------------------------------ #
# Currency and leakage                                                #
# ------------------------------------------------------------------ #

def test_a_filtered_page_shows_no_dollar_signs(client):
    login(client)
    today = date.today()
    body = profile_text(
        client, start=today.replace(day=1).isoformat(), end=today.isoformat()
    )

    assert "$" not in body
    assert "USD" not in body
    assert "18240.0" not in body


def test_an_empty_range_shows_no_dollar_signs(client):
    login(client)
    start, end = last_month()
    body = profile_text(client, start=start.isoformat(), end=end.isoformat())

    assert "$" not in body
    assert "USD" not in body


def test_no_filtered_page_renders_the_password_hash(client):
    login(client)
    today = date.today()
    start, end = last_month()

    for params in (
        {},
        {"start": today.replace(day=1).isoformat(), "end": today.isoformat()},
        {"start": start.isoformat(), "end": end.isoformat()},
        {"start": "2026-13-45", "end": "x"},
    ):
        body = profile_text(client, **params)
        assert "pbkdf2" not in body
        assert "scrypt" not in body
