# Spec: Add Expense

## Overview

Every step so far has read the `expenses` table; none has written to it. The
eight rows the app displays were put there by `seed_db()`, which means the whole
of Spendly currently depends on data no user could have entered. Step 7 closes
that gap: a signed-in user fills in an amount, a category, a date and an optional
note, and a row lands in `expenses` scoped to their account. It is the first
step where **user input becomes a row rather than a query**, and it is the first
`INSERT` outside registration — so it is where the validation habits the rest of
expense CRUD will copy get set. The important lesson is that a `<select>` and a
`type="number"` field are conveniences for the browser and not controls: the
category is checked against `CATEGORIES` on the server, the amount is parsed on
the server, and both are bound as parameters. Step 8 (edit) and Step 9 (delete)
will reuse this form's shape, its validation and its CSS, so the work here is
deliberately a little more careful than one form needs.

## Depends on

- **Step 1 — Database Setup.** Requires `get_db()`, the `expenses` table
  (`database/db.py:63-71`), and `CATEGORIES` (`database/db.py:39-47`) — the
  comment there says "later steps populate their dropdowns from this list", and
  this is that step. Also requires `format_inr` / the `inr` filter
  (`app.py:20`). Present on `main`.
- **Step 3 — Login and Logout.** Supplies `session["user_id"]`, which is the
  only source of `expenses.user_id` on the insert. Merged to `main`.
- **Step 4 — Profile Page Design.** Supplies the `/profile` page this route
  redirects back to, and the aggregates that will immediately reflect the new
  row. Merged to `main`.
- **Step 5 — Account Management.** Supplies the entire form vocabulary this step
  reuses — `.profile-form-card`, `.profile-form-actions`, `.profile-form-hint`,
  `.form-group`, `.form-input`, `.btn-submit`, `.btn-ghost` — plus the
  GET-then-POST route shape with a nested `reject()` helper
  (`app.py:369-463`), and the `?updated=1` / `?password=1` success-notice
  pattern (`templates/profile.html:9-19`) that `?added=1` follows. Merged to
  `main`.
- **Step 6 — Date Filter.** Supplies `parse_range()` and the habit of validating
  a date with `date.fromisoformat()` inside `try/except ValueError`
  (`app.py:160-189`). This step parses a single date, not a range, and must
  **not** try to reuse `parse_range()` — see the rules below. Merged to `main`.

The seeded demo account (`demo@spendly.com` / `demo123`) is what makes this
verifiable end to end: it already holds eight expenses totalling `₹18,240`, so a
successful add is visible as a changed count and a changed total on `/profile`
the moment the redirect lands.

## Routes

- `GET /expenses/add` — render the empty add-expense form, category dropdown
  populated from `CATEGORIES` and the date field defaulted to today —
  **logged-in only**
- `POST /expenses/add` — validate and insert one row, then redirect to
  `/profile?added=1` — **logged-in only**

Both replace the placeholder at `app.py:701-703`
(`"Add expense — coming in Step 7"`), which is deleted along with its position
under the "Placeholder routes" banner. The route keeps its existing URL and
its existing function name `add_expense` — `url_for('add_expense')` is the only
way templates should build the link.

One route, two methods, matching every form in the app since Step 2. On success
it **redirects** rather than rendering: a POST that returns HTML leaves the
insert sitting in the browser's history, where a refresh silently adds the
expense a second time. On failure it re-renders with an error and the submitted
values still in the fields.

`GET /expenses/<int:id>/edit` and `GET /expenses/<int:id>/delete` keep their
"coming in Step 8 / Step 9" strings and stay under the "Placeholder routes"
banner. Do not implement them here, and do not add a list route — `/profile` is
where the new row is observed for now, and an expense list is its own step.

## Database changes

**No database changes.** Every column this step writes already exists in
`database/db.py:63-71`, and `seed_db()` already inserts exactly this shape
(`database/db.py:213-217`) — the new route's `INSERT` should look like that one:

- `expenses.user_id` — `NOT NULL REFERENCES users(id) ON DELETE CASCADE`; comes
  from `session["user_id"]` and nowhere else
- `expenses.amount` — `REAL NOT NULL`; rupees as a float, not paise as an
  integer (`database/db.py:85`)
- `expenses.category` — `TEXT NOT NULL`; one of `CATEGORIES`, enforced in Python
  because SQLite has no `CHECK` constraint here and adding one is out of scope
- `expenses.date` — `TEXT NOT NULL` in ISO `'YYYY-MM-DD'`; the format Step 6's
  filter compares lexicographically, so a row stored any other way would be
  invisible to it
- `expenses.description` — the one nullable column; blank input stores `NULL`,
  not `''`
- `expenses.created_at` — `DEFAULT (datetime('now'))`, i.e. UTC. Leave it out of
  the `INSERT` column list entirely and let the default fire; do not pass
  `date.today()` or a local timestamp into it (`database/db.py:88-91`).

`SCHEMA` must not be touched. The `CREATE TABLE` statements are
`IF NOT EXISTS`, so any edit would silently do nothing on a developer database
that already exists and would require deleting `spendly.db` to take effect.

Note the column is named `date` and `app.py` imports `date` from `datetime`
(`app.py:3`). Do not shadow that import with a local variable named `date` —
the route needs `date.fromisoformat` and `date.today`.

## Templates

**Create:**

- `templates/expense_add.html` — extends `base.html`. Follows
  `profile_edit.html` almost line for line: an `h1.profile-name` heading, a
  `p.profile-meta` line of context, the `{% if error %}` → `.auth-error` block,
  then a `.profile-form-card` wrapping `<form method="POST">` with four
  `.form-group` fields and a `.profile-form-actions` row holding
  `button.btn-submit` ("Save expense") and a `.btn-ghost` Cancel link back to
  `/profile`. The fields:
  - **Amount** — `<input type="number" name="amount" step="0.01" min="0.01"
    inputmode="decimal" class="form-input" autofocus>` with a
    `.profile-form-hint` naming the unit in rupees
  - **Category** — `<select name="category" class="form-input form-select">`
    with one `<option>` per entry in `CATEGORIES`, looped, plus a disabled
    placeholder option so nothing is silently pre-selected
  - **Date** — `<input type="date" name="date" class="form-input">`, defaulted
    to today on a fresh GET
  - **Description** — `<input type="text" name="description"
    class="form-input">`, labelled optional in its own hint

**Modify:**

- `templates/profile.html` —
  - add an `{% if request.args.get('added') %}` `.auth-success` notice
    ("Your expense has been added.") as a third sibling of the two at lines
    9-19, not an `{% elif %}`
  - add `<a class="btn-ghost" href="{{ url_for('add_expense') }}">Add
    expense</a>` as the **first** control in `.profile-actions` (line 32-35);
    the row already `flex-wrap`s, so no CSS change is needed for it
  - give both empty states a link to the form: the first-run
    `.profile-empty` body (lines 127-133) should offer "Add your first expense",
    and the filtered `.profile-empty-filtered` body (lines 119-125) keeps its
    "show all time" link and gains the add link beside it

`base.html` needs **no change**. The nav stays at Analytics / name / Log out —
`.profile-actions` is where the account's everyday controls live, and adding a
fourth nav item for a form reachable in one click from there would buy nothing.

## Files to change

- `app.py` —
  - import `CATEGORIES` from `database.db` (line 8; the import list is
    alphabetical, so it goes first)
  - add an `# Expenses` section banner in the existing comment-banner style,
    after `logout()` and **above** the "Placeholder routes" banner, and
    implement `add_expense()` there
  - delete the `/expenses/add` stub at lines 701-703
  - add one module-level constant for the amount ceiling and one for each
    reusable error string, beside the route, following how `EMAIL_TAKEN`
    (line 46) and `RANGE_INVALID` / `RANGE_BACKWARDS` (lines 156-157) are
    declared
  - leave `profile()`, `parse_range()`, the account routes and the two
    remaining placeholders untouched
- `templates/profile.html` — the three changes listed above.
- `static/css/style.css` — add a `.form-select` rule in the existing
  `/* Auth pages */` section beside `.form-input` (`:566-581`), since a styled
  `<select>` is form vocabulary and not a profile-page component: it inherits
  `.form-input`'s box and only needs the appearance reset, a custom caret and
  `cursor: pointer` so it does not render as an unstyled native control next to
  the text inputs. No new top-level section. No new colour literals — the caret
  uses an existing `--ink*` variable.

## Files to create

- `templates/expense_add.html` — described above.
- `tests/test_add_expense.py` — the validation, scoping and access-control cases
  from the Definition of done, following the fixture style in
  `tests/test_filter.py` and `tests/test_account.py`. `tests/conftest.py`
  already redirects `SPENDLY_DB` at a scratch file, so no new fixture plumbing
  is needed.

## New dependencies

**No new dependencies.** `datetime.date` parses the date, the built-in `float`
parses the amount, and `math.isfinite` rejects the two float literals that would
otherwise slip through — all standard library. Do not add WTForms,
Flask-WTF, `marshmallow`, a decimal-money package or a date-picker JS library.
`<input type="date">` and `<select>` are native, and `static/js/main.js` stays
untouched.

## Rules for implementation

- **No SQLAlchemy or ORMs.** Raw `sqlite3` through `get_db()`, as in Steps 2-6.
- **Parameterised queries only.** The `INSERT` binds all five values as `?`
  placeholders — never an f-string, never `%` formatting, never `.format()`.
  Both the description and the category are attacker-controlled text; the
  category being whitelisted does not make it safe to concatenate, and nothing
  in this route may build SQL from user input.
- **Passwords hashed with werkzeug** — unchanged; this step touches no
  credential code.
- **`user_id` comes from the session, never from the form.** No hidden
  `user_id` field, no `?user=` parameter, no accepting an id in the body — the
  same reasoning as the comment in `profile_edit.html` ("the account being
  edited comes from the session, never from anything the page can send back").
  A form that could name its owner is how one account writes rows into
  another's ledger.
- **Apply the login guard first, before `request.form` is read.** Copy the shape
  from `profile_edit()` (`app.py:380-382`): read `session.get("user_id")`,
  redirect to `login` when absent. It must guard the POST as well as the GET —
  anything can POST straight at this URL without ever loading the form.
- **Validate on the server, every field, every time.** The template's
  `required`, `min` and `step` attributes and the `<select>`'s fixed options are
  browser conveniences and are trivially bypassed. Specifically:
  - **Amount** — reject blank; parse with `float()` inside
    `try/except ValueError`; reject anything not `math.isfinite()` (`float("inf")`
    and `float("nan")` both parse happily and would poison every `SUM` on
    `/profile` forever); reject `<= 0`; reject above the stated ceiling; then
    `round(..., 2)` before binding, because `amount` is `REAL` and storing
    unrounded input makes the totals drift. A single ceiling constant with a
    comment explaining it is a typo guard, not a business rule.
  - **Category** — must be `in CATEGORIES`. This check is the point of the
    field: a POST naming `"Bribes"` or `"Food'; DROP TABLE"` is rejected, not
    stored. Never trust that the value came from the rendered `<select>`.
  - **Date** — reject blank; parse with `date.fromisoformat()` inside
    `try/except ValueError`, exactly as `parse_range()` does; reject a date in
    the future against `date.today()` — you cannot have spent money tomorrow,
    and `seed_db()` deliberately never dates a row ahead
    (`database/db.py:158-176`). Re-serialise with `.isoformat()` so what is
    bound is always canonical `YYYY-MM-DD`.
  - **Description** — optional. `.strip()` it, cap its length (state the cap and
    reject beyond it rather than silently truncating), and bind `None` when it
    is empty so the nullable column holds `NULL` rather than `''`. Never strip
    the amount into a number by hand or strip a password anywhere.
- **Do not reuse `parse_range()`.** It answers a different question — two
  optional bounds where blank means unbounded — and this field is a single
  required date. Bending it to serve both would make blank silently valid here.
  Parse the one date inline in the route.
- **One `reject()` closure, re-rendering with the submitted values.** Follow
  `register()` (`app.py:66-72`) and `profile_edit()` (`app.py:410-414`): a
  nested helper that returns `render_template("expense_add.html", error=...)`
  with `amount`, `category`, `date` and `description` echoed back as the raw
  submitted strings, so a corrected typo does not mean retyping the form. The
  date field will only display canonical `YYYY-MM-DD`, so echo the raw string
  when it failed to parse and the re-serialised one when it did — the same
  compromise `profile()` makes at `app.py:343-344`.
- **Error messages in the project's existing voice**, reusing wording where the
  situation is the same: "Please fill in every field." is already the phrase for
  a missing field in both `register()` and `profile_edit()`, and must not be
  reworded here. New messages are plain sentences naming the one thing that is
  wrong — "Please enter an amount greater than zero.", "Please choose a category
  from the list.", "Please enter the date as YYYY-MM-DD.", "That date is in the
  future." Declare the ones used from more than one branch as module-level
  constants, as `EMAIL_TAKEN` is.
- **Close the connection in a `finally`.** `with get_db() as conn` commits but
  does not close (see the `get_db()` docstring); every route in `app.py` closes
  by hand and carries the same comment. Do the same, and `conn.commit()` after
  the insert — an insert that is never committed is the quietest possible
  failure.
- **Redirect on success, to `url_for("profile", added=1)`.** Not `render_template`,
  not `url_for("add_expense")`. `/profile` is where the effect of the insert is
  visible, and `?added=1` matches the `?updated=1` / `?password=1` notices Step 5
  established. Do not attach range parameters to the redirect.
- **The GET defaults the date to today and nothing else.** Amount blank,
  category on its disabled placeholder, description blank. Pre-filling an amount
  would be a guess; pre-filling the date is the overwhelmingly common case.
- **Categories come from `CATEGORIES`, looped in the template.** No hardcoded
  `<option>` list, in the template or the route — `database/db.py:37-38` says the
  two must stay in sync, and the only way to guarantee that is to have one
  source. Pass the list into the template and iterate.
- **Use CSS variables — never hardcode hex values.** `--ink*` / `--paper*` /
  `--accent*` / `--border*` / `--radius-*` / `--font-*`, plus `--danger` /
  `--danger-light` via the existing `.auth-error`. The `<select>` caret must be
  drawn with an existing variable or a border trick, not a new colour literal
  and not an external icon font.
- **Reuse the existing vocabulary** — `.profile-form-card`,
  `.profile-form-actions`, `.profile-form-hint`, `.form-group`, `.form-input`,
  `.btn-submit`, `.btn-ghost`, `.auth-error` — rather than inventing parallel
  classes. `.form-select` is the one new selector and it sits beside
  `.form-input`.
- **All templates extend `base.html`** and use its `{% block %}` slots. No
  second `<nav>` or `<footer>`, and `{% block title %}` reads
  "Add expense — Spendly".
- **No JavaScript.** No live currency formatting, no client-side validation, no
  category autocomplete. The form submits natively; a step that quietly
  introduced a JS dependency would break the no-build premise of the scaffold.
- Currency stays **INR** — the hint says rupees, any amount echoed in copy goes
  through the `inr` filter, and no `$` or `USD` appears anywhere.
- **CSRF protection is out of scope**, consistently with every other form in the
  project. Do not add a token to this form alone — a half-covered app is worse
  than an evenly uncovered one, and it belongs in its own step.
- Existing behaviour must not regress: `?updated=1` and `?password=1` keep
  working, Step 6's filter still applies on `/profile` after a redirect that
  carries only `added=1`, and the two remaining `/expenses/*` placeholders still
  return their strings.
- The form must render correctly at a 375px viewport width.
  `.profile-form-card` is already `max-width`-based and fluid
  (`static/css/style.css:802-811`), so this should need no new media query —
  verify rather than assume, and if the `<select>` overflows, fix it in the
  existing `@media (max-width: 600px)` block (`:994+`).

## Definition of done

Run `python app.py` and visit `http://localhost:5001`, signed in as
`demo@spendly.com` / `demo123`. Note the baseline: 8 expenses, `₹18,240`.

1. `/profile` shows an "Add expense" control in the actions row, and it links to
   `/expenses/add`.
2. `/expenses/add` renders the form — amount, a category dropdown listing all
   seven `CATEGORIES` entries and nothing else, a date field already showing
   today, and an optional description — styled consistently with
   `/profile/edit`, with the dropdown matching the text inputs rather than
   rendering as a native unstyled control.
3. Submitting amount `250`, category `Food`, today's date and a description
   redirects to `/profile?added=1`, shows "Your expense has been added.", and
   the tiles now read 9 expenses and `₹18,490`.
4. The new row appears in the category breakdown under `Food`, and the bar
   widths have redrawn.
5. Submitting with the description left blank succeeds, and the stored
   `description` is `NULL` — not an empty string. Verify with
   `venv/bin/python -c` over `get_db()`, or `sqlite3 spendly.db "SELECT
   description FROM expenses ORDER BY id DESC LIMIT 1"`.
6. A decimal amount (`99.50`) is stored and displayed correctly; `99.999`
   rounds to `100.00` rather than storing unrounded.
7. Each field missing on its own is rejected with an error, the form re-renders
   with the other values still filled in, and **no row is inserted** (the
   `/profile` count is unchanged).
8. Amount `0`, `-50`, `abc`, `1e400`, `inf` and `nan` are each rejected with a
   readable error and no traceback, no 500, and no row inserted. Bypass the
   browser's `type="number"` validation with
   `curl -X POST -d 'amount=nan&category=Food&date=2026-07-30' …` or the test
   client — the server, not the input element, must be what refuses them.
9. An amount above the stated ceiling is rejected with an error naming the
   limit.
10. `POST /expenses/add` with `category=Bribes` — a value the rendered
    `<select>` never offered — is rejected and inserts nothing. So is
    `category=` blank.
11. `POST /expenses/add` with `date=2026-13-45`, `date=tomorrow` or a date after
    today is rejected with the relevant error and inserts nothing.
12. `POST /expenses/add` with `description` containing `'); DROP TABLE
    expenses; --` stores that text verbatim as a description and leaves the
    schema intact — `/profile` still renders and the table still exists.
13. `POST /expenses/add` carrying an extra `user_id=2` field inserts the row
    against the **signed-in** user, not user 2. Confirm user 2's totals are
    unchanged (create a second account to check, or query the table directly).
14. Logged out, `GET /expenses/add` redirects to `/login`, and
    `POST /expenses/add` with a valid payload also redirects to `/login` and
    inserts nothing.
15. Adding an expense dated inside a range, then applying that range on
    `/profile`, shows the new expense inside the window — and a range that
    excludes its date does not. Step 6's filter still behaves.
16. Refreshing the page after the post-success redirect does **not** add a
    second copy of the expense.
17. An account with no expenses at all can add its first one from the link in
    the "No expenses yet" empty state, and the page switches from the empty
    state to the stats on the redirect.
18. `created_at` on the new row is a UTC `datetime('now')` value from the column
    default, not a date supplied by the route.
19. `venv/bin/python -m pytest` passes, including the new
    `tests/test_add_expense.py`. (Note: bare `pytest` fails collection — the
    project root is not on `sys.path`.)
20. `/expenses/1/edit` and `/expenses/1/delete` still return their
    "coming in Step 8" / "coming in Step 9" strings.
21. Every page still renders correctly at a 375px viewport width, with no
    horizontal overflow on the form or the dropdown.
