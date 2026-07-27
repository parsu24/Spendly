# Spec: Profile Page Design

## Overview

Step 4 gives a signed-in user their first page that is *theirs*. Login (Step 3)
put `user_id` in the session; until now nothing reads it back out. `/profile`
turns that session key into a real page: it looks the account up in `users`,
shows who they are and when they joined, and summarises the rows already sitting
in `expenses` — lifetime total, this month's total, expense count, and a
per-category breakdown. It is deliberately **read-only**. No form, no editing,
no new tables. Its job is to establish the two patterns every later logged-in
feature depends on: a **login-required guard** that turns an anonymous visit
into a redirect, and **user-scoped queries** that never read a row belonging to
someone else. Expense CRUD (Steps 7–9) writes the data this page is already
prepared to display, so once those steps land the profile fills out on its own
with no further change.

## Depends on

- **Step 1 — Database Setup.** Requires `get_db()`, the `users` and `expenses`
  tables, and the `to_local()` and `format_inr()` helpers in `database/db.py`.
  `to_local()`'s docstring names this page as its intended caller. Present on
  `main`.
- **Step 2 — Registration.** Supplies the accounts and the
  `.auth-*` / `.form-*` design vocabulary. Merged to `main`.
- **Step 3 — Login and Logout.** Supplies `SECRET_KEY`, `session["user_id"]`,
  `session["name"]`, and the conditional nav in `base.html`. Without it there is
  no identity to build a profile around. Merged to `main`.

The seeded demo account (`demo@spendly.com` / `demo123`, eight expenses
totalling ₹18,240) is what makes this page reviewable before Step 7 exists.

## Routes

- `GET /profile` — render the signed-in user's account details and spending
  summary; replaces the `"Profile page — coming in Step 4"` placeholder —
  **logged-in only**. An anonymous visitor is redirected to `GET /login`.

No other new routes. `/expenses/*` keeps its placeholder strings.

### Access-control behaviour

- No `session["user_id"]` → `redirect(url_for("login"))`.
- A `session["user_id"]` that matches no row in `users` — a stale cookie left
  over from a rebuilt `spendly.db`, which happens routinely in development —
  must `session.clear()` and redirect to `login` rather than raise or render a
  half-empty page.

## Database changes

**No database changes.** Every value on the page is derived from the existing
schema in `database/db.py`:

| source | used for |
| --- | --- |
| `users.name`, `users.email` | identity header |
| `users.created_at` (UTC) | "Member since", via `to_local()` |
| `expenses.amount` | lifetime total, this-month total, category totals |
| `expenses.date` (ISO `YYYY-MM-DD`) | this-month filter, first/latest activity |
| `expenses.category` | the breakdown, grouped against `CATEGORIES` |

No new columns, indexes, or constraints. `CREATE TABLE IF NOT EXISTS` means the
schema block is untouched.

## Templates

**Create:**

- `templates/profile.html` — extends `base.html`, fills `{% block title %}`
  (`Profile — Spendly`) and `{% block content %}`. Three regions:
  1. **Account header** — name, email, "Member since <date>". An avatar-style
     monogram built from the first letter of the name (CSS, not an image file).
  2. **Summary stats** — a row of stat cards: Total spent, This month, Expenses
     recorded, Top category. Mirrors the existing `.dash-stat` composition from
     the landing hero so the two pages read as one product.
  3. **Category breakdown** — one row per category that has spending, each with
     a label, an amount, and a proportional bar. Follows the
     `.dash-bar-row` / `.dash-bar-track` / `.dash-bar` structure already in the
     stylesheet.

**Modify:**

- `templates/base.html` — inside the existing `{% if session.user_id %}` branch
  of `.nav-links`, make the `.nav-user` name a link to `url_for('profile')`
  instead of a bare `<span>`. Keep the logged-out branch untouched.

## Files to change

- `app.py`
  - Widen the `database.db` import to bring in `format_inr` and `to_local`
    alongside `get_db`.
  - Register `format_inr` as a Jinja filter (`app.jinja_env.filters["inr"]`)
    right after the app is configured, so templates can write
    `{{ total | inr }}` and Steps 7–9 inherit rupee formatting for free. This is
    the one place currency formatting is wired up — no `₹` string-building in
    routes or templates.
  - Move the `/profile` route out of the "Placeholder routes" banner and up into
    the real routes section, replacing the placeholder string with the real
    implementation: guard, queries, `render_template("profile.html", ...)`.
  - Leave the `/expenses/*` placeholders and their banner comment in place.
- `templates/base.html` — profile link in the signed-in nav (above).
- `static/css/style.css` — a new `/* Profile page */` section placed **after**
  the Auth section and **before** the Footer section, matching the existing
  banner-comment style. Plus category colour custom properties added to `:root`
  and two entries in the existing responsive block.

## Files to create

- `templates/profile.html`
- `tests/test_profile.py` — the access-control and data-correctness cases from
  the Definition of done that are cheaper to assert than to click through.

## New dependencies

**No new dependencies.** Everything needed — Flask, Jinja2, `sqlite3`,
`datetime` — is already in `requirements.txt` or the standard library.

## Rules for implementation

- **No SQLAlchemy or ORMs.** Raw `sqlite3` through `get_db()`, as in Steps 2–3.
- **Parameterised queries only** — never f-strings or `%` formatting into SQL.
  This applies to the date-range bounds too; pass ISO strings as parameters.
- Passwords hashed with werkzeug. This step neither reads nor writes
  `password_hash`; do not `SELECT` it, and never put it in a template context.
- **Every expense query must be scoped with `WHERE user_id = ?`** against
  `session["user_id"]`. A query that could return another user's row is a bug
  even when the page happens to render correctly for the demo account.
- Never trust a route parameter or form field for identity — the user is
  whoever `session["user_id"]` says. `/profile/<int:requested_id>` exists as a
  second address for this page, but the id in it is only ever allowed to name
  the signed-in account: it is compared against the session and `abort(404)`s
  on any mismatch, and no query is ever scoped to it. A route that *read* from
  a URL id would be the bug this rule is about.
- Close the connection in a `finally`. `with get_db() as conn` commits but does
  not close; the Step 1 docstring spells this out.
- Aggregate in SQL (`COUNT`, `SUM`, `GROUP BY`), not by pulling every row into
  Python and looping. Wrap sums in `COALESCE(SUM(amount), 0)` so a user with no
  expenses gets `0`, not `None`.
- Run `users.created_at` through `to_local()` before display — stored values are
  UTC, so an IST reader would otherwise see a timestamp five and a half hours
  early. Never convert on the way in.
- **Currency is INR.** All amounts render through the `inr` filter
  (`format_inr`), giving Indian digit grouping and the `₹` symbol — `₹18,240`,
  never `$` or `USD`, never Python's `{:,}`.
- **Use CSS variables — never hardcode hex values.** The category bars need
  seven colours; add them to `:root` as `--cat-food`, `--cat-transport`,
  `--cat-bills`, `--cat-health`, `--cat-entertainment`, `--cat-shopping`,
  `--cat-other` and reference them from modifier classes. Do not copy the
  literal hexes from the existing `.dash-bar-food` rules into new selectors.
  Every other value comes from the existing `--ink*` / `--paper*` / `--accent*`
  / `--radius-*` / `--font-*` properties.
- The one legitimate inline style is a bar's `width` percentage, which is
  data-driven and cannot live in the stylesheet. Everything else is a class.
- Reuse existing component classes where the composition already exists rather
  than inventing parallel ones; new selectors are namespaced `.profile-*`.
- **All templates extend `base.html`** and use its `{% block %}` slots. Do not
  add a second `<nav>` or `<footer>`.
- The category order in the breakdown comes from `CATEGORIES` in
  `database/db.py` — that list is the single source of truth, so a category
  added there must not require a template edit.
- Handle the empty state deliberately: a brand-new account with zero expenses
  gets a short prompt, not `₹0` repeated four times over an empty chart.
- The page must be responsive — stat cards collapse on narrow screens like
  `.dash-stats` already does at 900px.
- Copy stays in the project's voice: "Spendly", rupee-oriented, plain sentences.
- Leave the `/expenses/*` placeholders untouched — their "coming in Step N"
  strings are the roadmap.

## Definition of done

Run `python app.py` and visit `http://localhost:5001`:

1. Visiting `/profile` while **logged out** redirects to `/login` — no traceback,
   no partial render, no data leaked.
2. Signing in as `demo@spendly.com` / `demo123` and visiting `/profile` renders
   the page with the nav showing the signed-in state.
3. Clicking the user's name in the nav navigates to `/profile`.
4. The header shows `Demo User` and `demo@spendly.com`, and a "Member since"
   date that matches when the demo row was seeded — converted to local time, not
   shown five and a half hours early.
5. **Total spent reads `₹18,240`** — the seeded total, with the `₹` symbol and
   Indian digit grouping. No `$`, no `USD`, no `18,240.0`.
6. "Expenses recorded" reads `8`.
7. "This month" equals `₹18,240` for the seeded data, since `seed_db()` spreads
   every sample expense across the current month.
8. The category breakdown lists Food (`₹6,630`), Shopping, Transport, Bills,
   Health, Other, and Entertainment — each with a bar whose width is
   proportional to its share, the widest bar belonging to Food.
9. "Top category" reads `Food`.
10. Registering a brand-new account and visiting `/profile` shows that account's
    name and email with the zero-expense empty state — not the demo user's
    figures, and not a crash on a `None` sum.
11. Deleting `spendly.db`, restarting, and reloading `/profile` with the old
    session cookie still present redirects to `/login` instead of raising.
12. The page uses the site's fonts, colours, and spacing — it looks like it
    belongs beside the landing page, and `git diff` on `style.css` contains no
    raw hex outside the `:root` block.
13. At a 600px-wide viewport the stat cards stack, nothing overflows
    horizontally, and the category bars stay legible.
14. `pytest` passes, including the new `tests/test_profile.py` and the existing
    `tests/test_db.py`, `tests/test_register.py`, and `tests/test_login.py`.
15. `git diff` touches only the files listed above — `/expenses/*` placeholders
    and the Step 1–3 code are unchanged.
