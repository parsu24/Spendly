# Spec: Date Filter for Profile Page

## Overview

Step 4 built the profile page and Step 5 gave it the write side of the account,
but the numbers on it have only ever meant one thing: *everything you have ever
spent*. Step 6 puts a date range in front of them. A signed-in user picks a start
and an end date — or clicks a preset — and the totals, the count, the top
category and the category bars all re-compute for that window. It is the first
step where **user input shapes a query rather than a row**, which makes it the
right place to establish the habits expense CRUD will lean on: input read from
the query string is parsed and validated before it goes anywhere near SQL, the
range is bound as parameters to a `BETWEEN` and never formatted into the
statement, and a filter that produces nothing says so distinctly from an account
that has nothing. No new routes, no new tables — `/profile` learns to read two
query parameters, and `expenses.date` was stored as sortable ISO text in Step 1
precisely so this step could be a `BETWEEN` and not a date library.

## Depends on

- **Step 1 — Database Setup.** Requires `get_db()`, the `expenses` table, and
  specifically `expenses.date TEXT` holding ISO `'YYYY-MM-DD'` — the note at
  `database/db.py:82-84` calls out that this is what makes `BETWEEN` correct for
  "the date-range filtering the landing page promises". This step is that
  promise. Also requires `format_inr` / the `inr` filter (`app.py:20`). Present
  on `main`.
- **Step 3 — Login and Logout.** Supplies `session["user_id"]`, which every
  query here stays scoped to. Merged to `main`.
- **Step 4 — Profile Page Design.** Supplies `GET /profile`, the three
  aggregate queries this step parameterises (`app.py:200-218`), the
  `categories` / `width` bar computation (`app.py:226-234`), the
  `.profile-*` and `.dash-stat*` CSS (`static/css/style.css:604-812`,
  `:242-278`), and the `.profile-empty` block this step gains a sibling to.
  Merged to `main`.
- **Step 5 — Account Management.** Supplies the `.profile-form-card` /
  `.form-input` / `.btn-ghost` form vocabulary the filter bar reuses, and the
  `?updated=1` query-string notice pattern (`templates/profile.html:9-19`) that
  proves the page already reads `request.args`. Merged to `main`.

The seeded demo account (`demo@spendly.com` / `demo123`) is what makes this
clickable: `seed_db()` spreads eight expenses across the days of the current
month so far (`database/db.py:158-176`), so a range covering this month returns
everything and a range covering last month returns nothing — both states are
reachable without adding a single row by hand.

## Routes

**No new routes.**

`GET /profile` and `GET /profile/<int:requested_id>` (`app.py:153-154`) gain two
optional query-string parameters — **logged-in only**, unchanged:

- `?start=YYYY-MM-DD` — inclusive lower bound; omitted or blank means unbounded
- `?end=YYYY-MM-DD` — inclusive upper bound; omitted or blank means unbounded

Both absent is the Step 4 behaviour exactly: all time, no filter applied. The
filter is a `GET` form, so the range lives in the URL and a filtered view is
bookmarkable, shareable back to yourself, and survives a refresh — none of which
a `POST` would give. There is no `POST /profile`; adding one is out of scope.

The presets are **links, not a third parameter**: each preset is an ordinary
`<a>` carrying a `start` and `end` already worked out server-side. That keeps
exactly one source of truth for the range and means the parsing code below has
one input shape to handle, not two.

The `/expenses/*` placeholders keep their "coming in Step N" strings.

## Database changes

**No database changes.** Every column this step reads already exists in
`database/db.py:63-71`:

- `expenses.date` — the filtered column; already `TEXT` in ISO `'YYYY-MM-DD'`,
  which sorts and compares lexicographically in SQLite, so
  `date BETWEEN ? AND ?` is both correct and index-friendly
- `expenses.amount`, `expenses.category`, `expenses.user_id` — already read by
  the three aggregates on `/profile`

`SCHEMA` must not be touched. Do **not** add an index, a `date` column of a
different type, or a generated month column: the `CREATE TABLE` statements are
`IF NOT EXISTS`, so any schema edit would require deleting `spendly.db` to take
effect and would silently do nothing on an existing developer database.

Note the column is named `date` and `app.py` imports `date` from `datetime`
(`app.py:3`). Do not shadow that import with a local variable named `date` —
the parsing helper needs `date.fromisoformat` and `date.today`.

## Templates

**Create:** none.

**Modify:**

- `templates/profile.html` — add a filter bar directly above `.profile-stats`
  containing: a `method="get"` form posting to `url_for('profile')` with two
  `<input type="date">` fields (`name="start"`, `name="end"`) pre-filled from
  the parsed range, an Apply submit and a "Clear" link back to bare `/profile`;
  a row of preset links; a `.auth-error` notice slot for an invalid range; a
  line stating which range is currently in force; and a second empty state for
  "no expenses **in this range**" that is distinct from the existing
  "No expenses yet". The four `.dash-stat` tiles and the category card keep
  their markup — they simply receive range-scoped numbers.

`base.html` needs **no change**. The nav already links to `/profile` and the
filter never leaves that page.

## Files to change

- `app.py` — extend `profile()`: parse `start` / `end` from `request.args`,
  build the range-scoped `WHERE` clause, pass the range and any error into the
  template. Add one module-level helper (see below) in the same section, above
  `profile()`. `date` is already imported (`app.py:3`); nothing new to import.
  Leave `/profile/edit`, `/profile/password`, `/profile/delete`, the
  "Placeholder routes" banner and its three stubs exactly as they are.
- `templates/profile.html` — the filter bar, the range line, the second empty
  state.
- `static/css/style.css` — extend the existing `/* Profile page */` section
  (`:604-812`) with `.profile-filter`, `.profile-filter-fields`,
  `.profile-filter-presets`, `.profile-range-note` and a modifier for the
  in-range empty state. Add the filter bar's collapse to the existing
  `@media` blocks in the Responsive section (`:860+`). Do not open a new
  top-level section and do not touch the Auth section.

## Files to create

- `tests/test_filter.py` — the parsing, scoping and access-control cases from
  the Definition of done, following the existing fixture style in
  `tests/test_profile.py` (`tests/conftest.py` already redirects `SPENDLY_DB`
  at a scratch file, so no new fixture plumbing is needed).

## New dependencies

**No new dependencies.** `datetime.date` from the standard library parses and
formats every value here; Flask's `request.args` reads them. Do not add
`python-dateutil`, `arrow`, `pendulum` or a date-picker JS library — `<input
type="date">` is native and `static/js/main.js` stays untouched.

## Rules for implementation

- **No SQLAlchemy or ORMs.** Raw `sqlite3` through `get_db()`, as in Steps 2–5.
- **Parameterised queries only.** The two bounds are bound as `?` parameters to
  a `BETWEEN`, never f-strings or `%` formatting into the SQL. This is the rule
  the whole step exists to teach: `start` and `end` arrive from the address bar,
  which makes them the most obviously attacker-controlled values in the project
  so far. A date that fails parsing must never reach the query at all.
- **Passwords hashed with werkzeug** — unchanged; this step touches no
  credential code.
- **Every query stays scoped to `session["user_id"]`.** The range narrows a
  result set that is *already* the signed-in user's; it never widens it.
  `WHERE user_id = ?` keeps its place as the first clause in all three
  aggregates, and the `requested_id != user_id` → `abort(404)` check
  (`app.py:185-186`) runs before any of this. A filter is not a reason to relax
  ownership.
- Apply the same login guard `/profile` already uses (`app.py:170-172`) — it is
  unchanged and must keep running **before** `request.args` is read.
- **Parse before you query.** Write one helper — `parse_range(args)` or
  similar — that turns `request.args` into `(start, end, error)` where the
  bounds are either ISO strings or `None`. Rules it must implement:
  - blank or missing on either side → `None`, meaning unbounded on that side;
    both `None` is the unfiltered Step 4 view
  - a value that is not a real ISO date → **ignore the whole filter** (fall back
    to all time) and return an error message for the template. Use
    `date.fromisoformat()` inside `try/except ValueError`; do not hand-roll a
    regex, and do not let a `ValueError` reach the browser as a 500. Note that
    `date.fromisoformat` accepts only `YYYY-MM-DD` for a `date`, which is
    exactly the stored format.
  - `start` later than `end` → same treatment: no filter, and a specific error
    saying the start date is after the end date. Do **not** silently swap them;
    a range typed backwards is a mistake worth reporting.
  - re-serialise with `.isoformat()` before it goes into SQL or back into the
    template, so what is bound is always canonical `YYYY-MM-DD` and never the
    raw string the visitor typed.
- **Build the `WHERE` from fixed fragments, not from user text.** Append
  `" AND date >= ?"` / `" AND date <= ?"` (both are string literals in the
  source) and extend the parameter tuple alongside them. One clause pair,
  assembled once and reused by all three aggregate queries, rather than three
  divergent hand-written variants — this is the part most likely to drift.
  `BETWEEN` is inclusive on both ends and that is the intended behaviour: an
  expense dated exactly on the boundary is in the range.
- **All three aggregates are filtered.** The count/total summary
  (`app.py:200-204`) and the category breakdown (`app.py:214-218`) both take the
  range. So does the tile currently labelled "This month" — see the next rule.
- **Replace the "This month" tile with "Average per expense".** Once a visitor
  can choose any window, a tile hard-wired to the calendar month contradicts the
  three beside it, and "This month" survives as a *preset* instead. The new tile
  is the range total divided by the range count, through the `inr` filter, and
  it must guard against a zero count. The `strftime('%Y-%m', date)` query at
  `app.py:208-212` is then dead and should be deleted rather than left
  unreferenced — but keep `date.today()` available, the presets need it.
- **Presets are computed server-side and rendered as links.** Provide: *This
  month* (1st of the current month → today), *Last 30 days* (today − 29 days →
  today), *This year* (1 January → today), and *All time* (a plain link to
  `/profile` with no parameters, which is also the Clear control). Build their
  URLs with `url_for('profile', start=..., end=...)` so escaping is Flask's job,
  never by concatenating a query string by hand.
- **`largest` must be recomputed from the filtered breakdown.** The bar widths
  are measured against the biggest category *in the current range*
  (`app.py:226-234`), so the top bar always fills its track. Keep the
  `if largest else 0` guard — an empty range makes it `0` and the division would
  otherwise raise.
- **An empty range is not an empty account.** `{% if count %}` currently splits
  "has expenses" from "No expenses yet". With a filter active, a zero count
  means *nothing in this window* and must say so, and must offer the way back —
  a "Clear filter" / *All time* link. Showing "No expenses yet" to an account
  holding eighteen thousand rupees of history because they picked last February
  is the single most likely bug in this step. Distinguish the two by whether a
  range is in force, not by re-querying.
- **The filter bar renders in every state** — with results, with an empty range,
  and on an account with no expenses at all. Place it above the `{% if count %}`
  split, the same reasoning that put `.profile-actions` there in Step 5
  (`templates/profile.html:30-35`).
- **Re-render the inputs with the parsed values still in place**, so Apply
  twice is idempotent and a corrected typo does not mean retyping both fields.
  When the range was rejected, show the error via the existing `.auth-error`
  block and leave the fields holding what was submitted.
- State the range in force in plain words above the stats — "Showing 1 Jul 2026
  to 29 Jul 2026", "Showing everything up to 29 Jul 2026", "Showing all time" —
  formatted the way `member_since` is (`app.py:241`), not as raw ISO.
- **Use CSS variables — never hardcode hex values.** `--ink*` / `--paper*` /
  `--accent*` / `--radius-*` / `--font-*`, plus `--danger` / `--danger-light`
  for the error notice, which `.auth-error` already supplies. No new colour
  literals anywhere.
- Reuse the existing vocabulary — `.form-input`, `.form-group`, `.btn-submit`,
  `.btn-ghost`, `.auth-error` — rather than inventing parallel classes. New
  selectors are namespaced `.profile-*`.
- **All templates extend `base.html`** and use its `{% block %}` slots. No
  second `<nav>` or `<footer>`.
- **No JavaScript.** `static/js/main.js` stays as it is; `<input type="date">`
  gives the picker for free and the form submits natively. A step that quietly
  introduced a JS dependency would break the no-build premise of the scaffold.
- Currency stays **INR** — every amount through the `inr` filter, never `$` or
  `USD`. Copy stays in the project's voice: "Spendly", plain sentences.
- Existing query-string notices must keep working: `?updated=1` and
  `?password=1` (`templates/profile.html:9-19`) are read by the same
  `request.args` this step now also reads, and the redirects in Step 5 must not
  be changed to carry range parameters.
- The filter bar must collapse cleanly at 900px and 600px alongside the existing
  profile layout (`static/css/style.css:860+`), stacking the two date fields
  rather than letting them overflow at 375px.

## Definition of done

Run `python app.py` and visit `http://localhost:5001`, signed in as
`demo@spendly.com` / `demo123`:

1. `/profile` with no query string renders exactly as before the change: all
   eight seeded expenses counted, total `₹18,240`, and every category bar
   present.
2. The filter bar appears above the stats with two empty date fields, the four
   presets, and an Apply button.
3. Picking a start of the 1st of this month and an end of today, then applying,
   lands on `/profile?start=…&end=…` with the range visible in the address bar,
   the fields still holding those dates, and the same eight expenses counted.
4. Narrowing the range to a two-day window inside this month reduces the count
   and the total, and the category bars redraw — the longest bar still fills its
   track.
5. A range covering **last** month returns zero expenses and shows the
   "no expenses in this range" message with a working clear/all-time link —
   **not** the "No expenses yet" empty state.
6. Clicking *All time* (or Clear) returns to bare `/profile` with the full
   totals and empty fields.
7. Each of *This month*, *Last 30 days* and *This year* loads a range whose
   dates are visible in both the URL and the fields, and whose totals are
   consistent with each other (this month ≤ this year).
8. Leaving `start` blank and setting only `end` filters on the upper bound
   alone; the reverse works for `start`.
9. `/profile?start=2026-13-45&end=x` renders the page with an error notice and
   **all-time** figures — no traceback, no 500.
10. `/profile?start=2026-07-29&end=2026-07-01` (start after end) reports that
    specific error and shows all-time figures rather than an empty result.
11. `/profile?start=2026-07-01%27%20OR%20%271%27%3D%271` — a quoted injection
    attempt in a bound parameter — is rejected as an unparseable date and
    changes nothing. The database is untouched.
12. The "Average per expense" tile equals the displayed total divided by the
    displayed count for whatever range is showing, and an empty range shows
    `₹0` rather than raising.
13. `/profile/1?start=…&end=…` works identically for the signed-in user, and
    `/profile/2?start=…&end=…` still returns **404** — the filter has not
    loosened the ownership check.
14. Logged out, `/profile?start=…&end=…` still redirects to `/login` and leaks
    nothing.
15. An account with no expenses at all still shows "No expenses yet" **and** a
    usable filter bar above it.
16. `venv/bin/python -m pytest` passes, including the new `tests/test_filter.py`.
    (Note: bare `pytest` fails collection — the project root is not on
    `sys.path`.)
17. Every page still renders correctly at a 375px viewport width, with the two
    date fields stacked rather than overflowing.
