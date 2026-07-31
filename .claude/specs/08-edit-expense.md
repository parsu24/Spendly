# Spec: Edit Expense

## Overview

Step 7 made a user's input into a row. Step 8 makes an existing row editable — the
first route in Spendly where **a value from the URL names a database record**. That
is the whole lesson here. Every route so far has been scoped to `session["user_id"]`
and nothing else; `/expenses/<int:id>/edit` takes an id a visitor can type, and the
only thing standing between that and reading or overwriting somebody else's expense
is a `WHERE id = ? AND user_id = ?` on every statement. `/profile/<int:requested_id>`
already rehearsed the reasoning (`app.py:256-267`) but had the luxury of comparing
the id against the session directly; here the id names a different table's row, so
ownership has to be established by the query itself. Step 8 also closes a gap Step 7
deliberately left open: nothing in the UI lists expenses, so a row, once added, can
only be seen as a number in a tile. This step adds a modest **"Recent expenses"**
list to `/profile` — which is what makes an edit link reachable at all, and what
Step 9's delete link will hang off next.

## Depends on

- **Step 1 — Database Setup.** Requires `get_db()`, the `expenses` table
  (`database/db.py:63-71`), `CATEGORIES` (`database/db.py:39-47`) and
  `format_inr` / the `inr` filter (`app.py:21`). Present on `main`.
- **Step 3 — Login and Logout.** Supplies `session["user_id"]`, which is the second
  half of every `WHERE` clause in this step. Merged to `main`.
- **Step 4 — Profile Page Design.** Supplies `/profile`, the page this route
  redirects back to and the page the new list is added to. Merged to `main`.
- **Step 5 — Account Management.** Supplies the form vocabulary — `.profile-form-card`,
  `.profile-form-actions`, `.profile-form-hint`, `.form-group`, `.form-input`,
  `.btn-submit`, `.btn-ghost` — the GET-then-POST route shape with a nested
  `reject()` helper (`app.py:370-464`), and the `?updated=1` / `?password=1`
  success-notice pattern (`templates/profile.html:11-25`) that `?edited=1` joins.
  Merged to `main`.
- **Step 6 — Date Filter.** Supplies `parse_range()` and the `clause` / `params`
  construction in `profile()` (`app.py:272-286`), which the new expense list must
  reuse so the list agrees with the tiles above it. Merged to `main`.
- **Step 7 — Add Expense.** Supplies everything this step edits: `add_expense()`
  (`app.py:721-870`), its validation, `AMOUNT_MAX`, `DESCRIPTION_MAX`,
  `AMOUNT_TOO_LARGE`, `DESCRIPTION_TOO_LONG`, `templates/expense_add.html` and
  `.form-select`. Merged to `main` as commit `641054b`.

The seeded demo account (`demo@spendly.com` / `demo123`) makes this verifiable end
to end: it holds eight expenses totalling `₹18,240`, so editing one is visible as a
changed total on `/profile` the moment the redirect lands.

## Routes

- `GET /expenses/<int:id>/edit` — render the edit form prefilled from the row, or
  **404** if that id is not this account's — **logged-in only**
- `POST /expenses/<int:id>/edit` — validate and `UPDATE` that one row, then redirect
  to `/profile?edited=1`; **404** on the same condition — **logged-in only**

Both replace the placeholder at `app.py:878-880`
(`"Edit expense — coming in Step 8"`), which is deleted along with its position
under the "Placeholder routes" banner. The route keeps its existing URL rule and its
existing function name `edit_expense` — `url_for('edit_expense', id=...)` is the only
way templates should build the link.

`GET /expenses/<int:id>/delete` keeps its "coming in Step 9" string and stays under
the "Placeholder routes" banner, which now holds one route. **No new list route.**
The expense list is a section of `/profile`, not a page of its own — `/expenses`
as a paginated list is its own step and is out of scope here.

**404, not 403, for an id that is not yours**, and the same 404 for an id that does
not exist. This is the reasoning `profile()` already carries at `app.py:262-267`:
"forbidden" would confirm the row exists, so a stranger could walk the ids and learn
how many expenses the app holds. "Not found" is the same answer for both and tells
them apart for nobody. `abort(404)` is already imported (`app.py:6`).

## Database changes

**No database changes.** Every column this step writes already exists in
`database/db.py:63-71`, and `add_expense()` already writes exactly this shape.

- `expenses.id` — the `INTEGER PRIMARY KEY` the URL names; used only inside a
  `WHERE` that also names `user_id`
- `expenses.user_id` — **never in the `SET` list.** An edit cannot move a row
  between accounts, and a route that could would be a way to plant rows in
  somebody else's ledger. It appears in the `WHERE` clause and nowhere else.
- `expenses.amount` — `REAL NOT NULL`; rounded to 2 dp before binding, as Step 7 does
- `expenses.category` — `TEXT NOT NULL`; one of `CATEGORIES`, enforced in Python
- `expenses.date` — `TEXT NOT NULL` in ISO `'YYYY-MM-DD'`, so Step 6's filter can
  still compare it lexicographically
- `expenses.description` — the one nullable column; blank input stores `NULL`, not `''`
- `expenses.created_at` — **never in the `SET` list.** It records when the expense
  was entered, not when it was last touched; overwriting it on an edit would make
  the column mean two different things depending on the row's history. There is no
  `updated_at` column and this step does not add one.

`SCHEMA` must not be touched. The `CREATE TABLE` statements are `IF NOT EXISTS`, so
any edit would silently do nothing on a developer database that already exists.

Note the column is named `date` and `app.py` imports `date` from `datetime`
(`app.py:4`). Do not shadow that import with a local variable named `date` — the
route needs `date.fromisoformat` and `date.today`.

## Templates

**Create:**

- `templates/expense_edit.html` — extends `base.html`, `{% block title %}` reads
  "Edit expense — Spendly". A near-twin of `expense_add.html` (the project keeps one
  template per page — `profile_edit.html` and `profile_password.html` are separate
  files with the same shape — so a separate file is the convention, not a shared
  partial). Differences from the add template, and they are the whole point:
  - the heading reads "Edit expense" and the `p.profile-meta` line names what is
    being changed rather than promising a new row
  - `<form method="POST" action="{{ url_for('edit_expense', id=id) }}">` — the id
    travels in the **URL only**. No hidden `<input name="id">`, no hidden
    `user_id`; carry the comment `expense_add.html:17-18` carries, adapted.
  - every field is prefilled from the row on a fresh `GET`
  - the category `<select>` keeps its looped `CATEGORIES` options and its disabled
    placeholder, but the row's category is always `selected`, so the placeholder is
    never reachable on this page
  - the submit button reads "Save changes"; the `.btn-ghost` Cancel link goes back
    to `/profile`

**Modify:**

- `templates/profile.html` —
  - add an `{% if request.args.get('edited') %}` `.auth-success` notice ("Your
    expense has been updated.") as a **fourth sibling** of the three at lines 11-25,
    not an `{% elif %}` — the existing comment there explains why
  - add a **"Recent expenses"** section: a second `.profile-card` immediately after
    the "Where your money goes" card, inside the same `{% if count %}` branch, with
    an `h2.profile-card-title` and one row per expense. Each row shows the date, the
    category, the description (or a dash when `NULL`), the amount through the `inr`
    filter, and an **Edit** link to `url_for('edit_expense', id=expense.id)`.
  - the filtered empty state (`.profile-empty-filtered`) and the first-run empty
    state keep their current copy unchanged — a range with no rows has no list to
    show, and the `{% if count %}` branch already handles that

`base.html` needs **no change**. `expense_add.html` needs **no change** beyond what
the shared-validation refactor below implies — which is nothing, if that refactor is
done correctly.

## Files to change

- `app.py` —
  - extract the field validation Step 7 wrote inside `add_expense()` into one
    module-level helper in the "Expenses" section, above both routes — suggested
    `parse_expense_form(form)` returning `(values, error)` where `values` is a dict
    of the cleaned `amount` / `category` / `date` / `description` and `error` is
    `None` or the message. Both routes call it; neither reimplements it. See the
    rules below for the constraints on this refactor.
  - implement `edit_expense(id)` in the "Expenses" section, below `add_expense()`
  - delete the `/expenses/<int:id>/edit` stub at lines 878-880
  - in `profile()`, add one more query returning this account's expense rows —
    `id`, `amount`, `category`, `date`, `description` — reusing the **existing**
    `clause` and `params` (`app.py:278-286`) so the list obeys the date filter, and
    pass the rows to the template. Order newest first (`ORDER BY date DESC, id DESC`)
    and cap it — a `LIMIT` constant with a comment saying the card is a recent-activity
    view and not the full ledger.
  - leave `parse_range()`, the account routes, `add_expense()`'s route body (beyond
    the extraction) and the remaining placeholder untouched
- `templates/profile.html` — the two changes listed above.
- `static/css/style.css` — add the expense-list rules to the existing
  `/* Profile page */` section (`:636-906`), beside `.profile-bar-row`, and one
  stacking rule in the existing `@media (max-width: 600px)` block (`:1020+`) if the
  row does not fit at 375px. No new top-level section, no new colour literals.

## Files to create

- `templates/expense_edit.html` — described above.
- `tests/test_edit_expense.py` — the ownership, validation and no-op cases from the
  Definition of done, following the fixture style in `tests/test_add_expense.py`
  (which already has `login`, `register` and `add` helpers worth mirroring).
  `tests/conftest.py` already redirects `SPENDLY_DB` at a scratch file, so no new
  fixture plumbing is needed.

## New dependencies

**No new dependencies.** `datetime.date` parses the date, the built-in `float`
parses the amount, `math.isfinite` rejects the float literals that would otherwise
slip through — all standard library and all already imported. Do not add WTForms,
Flask-WTF, `marshmallow`, a decimal-money package or any JS date picker.
`static/js/main.js` stays untouched.

## Rules for implementation

- **No SQLAlchemy or ORMs.** Raw `sqlite3` through `get_db()`, as in Steps 2-7.
- **Parameterised queries only.** The `SELECT`, the `UPDATE` and the new list query
  bind every value as a `?` placeholder — never an f-string, never `%` formatting,
  never `.format()`. The only string concatenation permitted anywhere near SQL is
  Step 6's `clause`, which is assembled from literals written in `app.py` and
  carries the comment explaining exactly that (`app.py:275-277`).
- **Ownership is enforced in the `WHERE` clause of every statement, not in Python.**
  Both the `SELECT` that loads the row and the `UPDATE` that writes it must carry
  `WHERE id = ? AND user_id = ?` with `user_id` from the session. Do not fetch by id
  alone and compare `row["user_id"]` afterwards — it works, but it puts the check one
  edit away from being dropped, and it means the row was read before the reader was
  entitled to it. Scoping the query is the habit this step exists to teach.
- **`abort(404)` when the `SELECT` returns nothing**, on both GET and POST, for
  both a nonexistent id and another account's id. Never 403, never a redirect, never
  a message distinguishing the two.
- **Apply the login guard first, before `request.form` is read**, and before the row
  is looked up. Copy the shape from `add_expense()` (`app.py:730-732`): read
  `session.get("user_id")`, redirect to `login` when absent. It must guard the POST
  as well as the GET — anything can POST straight at this URL without ever loading
  the form. A logged-out request must get the login redirect and **not** a 404, so
  the route never reveals whether the id exists to someone who is not signed in.
- **`user_id` comes from the session, never from the form or the URL.** No hidden
  `user_id` field, no `?user=` parameter. The `id` in the path names a row; it does
  not name an owner.
- **The refactor must not change `add_expense()`'s behaviour.**
  `tests/test_add_expense.py` passes today and must still pass **unmodified** after
  the extraction — that is the acceptance test for the refactor, and it is why the
  extraction comes first as its own reviewable change. Specifically: the same error
  strings in the same order of checks, the same `round(amount, 2)`, the same
  `description or None`, the same `AMOUNT_MAX` / `DESCRIPTION_MAX` constants. If
  sharing the validation would require weakening any check for either route, do not
  share it — duplicate it and say so in a comment. Correctness outranks tidiness.
- **The nested `reject()` closure stays per-route.** It re-renders that route's own
  template with that route's own context (the edit form needs `id` in its context so
  its `action` can be rebuilt; the add form does not). Only the *validation* is
  shared, not the rendering.
- **Validate on the server, every field, every time** — identical rules to Step 7,
  because the field is the same field: reject blank amount/category/date; parse the
  amount with `float()` inside `try/except ValueError`; reject anything not
  `math.isfinite()`; reject `<= 0` and above `AMOUNT_MAX`; `round(..., 2)` before
  binding; `category in CATEGORIES`; `date.fromisoformat()` inside
  `try/except ValueError`; reject a date after `date.today()`; cap the description at
  `DESCRIPTION_MAX` and reject rather than truncate; bind `None` for a blank
  description. An edit form that validates more loosely than the add form is a way to
  write a value the add form refuses.
- **Do not reuse `parse_range()`** for the single date field, for the reason Step 7's
  spec gives: it answers a different question and would make blank silently valid.
- **Error messages in the project's existing voice**, reusing Step 7's wording
  verbatim — "Please fill in every field.", "Please enter an amount greater than
  zero.", "Please choose a category from the list.", "Please enter the date as
  YYYY-MM-DD.", "That date is in the future." A visitor must not have to learn two
  vocabularies for one mistake. Reuse the existing `AMOUNT_TOO_LARGE` and
  `DESCRIPTION_TOO_LONG` constants; do not declare parallel ones.
- **A submit that changes nothing is a success, not an error.** Opening the form and
  pressing "Save changes" without touching a field must run the `UPDATE`, redirect,
  and leave the row exactly as it was. Do not add a "nothing changed" rejection — the
  change-password route's "must be different" rule exists because a password change
  that changes nothing is almost always a typo; re-saving an expense is not.
- **Close the connection in a `finally`.** `with get_db() as conn` commits but does
  not close (see the `get_db()` docstring); every route in `app.py` closes by hand
  and carries the same comment. `conn.commit()` after the `UPDATE` — an update that is
  never committed is the quietest possible failure.
- **Handle the stale-cookie case** the way every logged-in route does: if the account
  behind the session no longer exists, `session.clear()` and redirect to `login`. On
  this route the ownership-scoped `SELECT` already returns nothing for a deleted
  account, so a 404 would be *correct* but useless — check the user the way
  `add_expense()` does (`app.py:742-746`) so a rebuilt database sends the visitor to a
  fresh login instead.
- **Redirect on success, to `url_for("profile", edited=1)`.** Not `render_template`,
  not back to the edit form. A POST that answers with HTML leaves the update sitting
  in the browser's history. Do not attach range parameters to the redirect.
- **Categories come from `CATEGORIES`, looped in the template.** No hardcoded
  `<option>` list, in the template or the route.
- **The expense list on `/profile` obeys the date filter.** It reuses the same
  `clause` and `params` the tiles are built from — a list showing rows the tiles do
  not count would make the page contradict itself. It is also scoped to `user_id`
  like every other query on that page.
- **Escaping is Jinja's job and it is already doing it.** The description is
  attacker-controlled text rendered for the first time by this step's list; render it
  as `{{ expense.description }}` and do not reach for `|safe` anywhere.
- **Use CSS variables — never hardcode hex values.** `--ink*` / `--paper*` /
  `--accent*` / `--border*` / `--radius-*` / `--font-*`. The list rows must be built
  from the existing variables and the existing `.profile-card` box.
- **Reuse the existing vocabulary** — `.profile-card`, `.profile-card-title`,
  `.profile-form-card`, `.profile-form-actions`, `.profile-form-hint`, `.form-group`,
  `.form-input`, `.form-select`, `.btn-submit`, `.btn-ghost`, `.auth-error`,
  `.auth-success` — rather than inventing parallel classes. The expense-list rows are
  the only new selectors; name them in the established `.profile-*` style.
- **All templates extend `base.html`** and use its `{% block %}` slots. No second
  `<nav>` or `<footer>`.
- **No JavaScript.** No inline editing, no confirm dialog, no client-side validation.
  The form submits natively.
- Currency stays **INR** — every amount in the list and any amount echoed in copy
  goes through the `inr` filter, and no `$` or `USD` appears anywhere.
- **CSRF protection is out of scope**, consistently with every other form in the
  project. Do not add a token to this form alone.
- **Passwords hashed with werkzeug** — unchanged; this step touches no credential
  code, and editing an expense requires no re-authentication (it is recoverable, by
  the same reasoning `profile_edit()` sets out at `app.py:372-377`).
- Existing behaviour must not regress: `?updated=1`, `?password=1` and `?added=1`
  keep working, Step 6's filter still applies on `/profile`, `/expenses/add` behaves
  exactly as before, and `/expenses/1/delete` still returns its Step 9 string.
- The form and the new list must render correctly at a **375px** viewport width with
  no horizontal overflow. Verify rather than assume; if the list row does not fit,
  fix it in the existing `@media (max-width: 600px)` block.

## Definition of done

Run `python app.py` and visit `http://localhost:5001`, signed in as
`demo@spendly.com` / `demo123`. Baseline: 8 expenses, `₹18,240`.

1. `/profile` shows a "Recent expenses" card listing the account's expenses, newest
   first, each row showing its date, category, description, amount in `₹` with Indian
   grouping, and an **Edit** link.
2. A row whose `description` is `NULL` renders a dash or similar placeholder in the
   list — not the word "None", not an empty gap, and no traceback.
3. Clicking **Edit** on a row opens `/expenses/<id>/edit` with all four fields
   prefilled from that exact row: the amount, the category already selected in the
   dropdown, the date in the date field, and the description.
4. Changing the amount from `3450` to `4000` and saving redirects to
   `/profile?edited=1`, shows "Your expense has been updated.", and the total tile
   moves from `₹18,240` to `₹18,790`. The expense count stays **8** — an edit must
   not create a row.
5. Changing a row's category moves it between bars in "Where your money goes", and
   the bar widths redraw.
6. Opening the form and pressing "Save changes" without touching anything succeeds,
   redirects, and leaves the row byte-for-byte unchanged — including its
   `created_at`. Verify `created_at` directly:
   `sqlite3 spendly.db "SELECT id, created_at FROM expenses WHERE id = 1"` before and
   after.
7. Clearing the description and saving stores `NULL`, not `''`:
   `sqlite3 spendly.db "SELECT description IS NULL FROM expenses WHERE id = 1"`
   returns `1`.
8. Each field cleared on its own is rejected with an error, the form re-renders with
   the other submitted values still filled in, and **the row is unchanged** in the
   database.
9. Amount `0`, `-50`, `abc`, `1e400`, `inf` and `nan` are each rejected with a
   readable error — no traceback, no 500 — and the row is unchanged. Use the test
   client or `curl -X POST -d 'amount=nan&category=Food&date=2026-07-30' …` to get
   past the browser's `type="number"` validation.
10. An amount above the ceiling is rejected with the same message
    `/expenses/add` gives, naming the limit.
11. `POST` with `category=Bribes` — a value the rendered `<select>` never offered —
    is rejected and the row is unchanged. So is `category=` blank.
12. `POST` with `date=2026-13-45`, `date=tomorrow` or a date after today is rejected
    and the row is unchanged.
13. `POST` with `description` containing `'); DROP TABLE expenses; --` stores that
    text verbatim, leaves the schema intact, and the text renders escaped in the
    `/profile` list rather than as markup.
14. **Ownership.** Register a second account, add an expense to it, then — signed in
    as the demo user — `GET /expenses/<that id>/edit` returns **404**, and `POST` to
    it returns 404 and leaves the other account's row **unchanged**. Confirm the row
    directly in the database, not just by the status code.
15. `GET /expenses/99999/edit` (an id that has never existed) returns 404, the same
    response as the previous case.
16. `POST /expenses/<own id>/edit` carrying an extra `user_id=2` field updates the row
    and leaves its `user_id` as the signed-in account. Confirm with
    `sqlite3 spendly.db "SELECT user_id FROM expenses WHERE id = <id>"`.
17. Logged out, `GET /expenses/1/edit` redirects to `/login` — **not** 404 — and
    `POST /expenses/1/edit` with a valid payload also redirects to `/login` and
    changes nothing.
18. Refreshing after the post-success redirect does not re-submit the edit or produce
    a second row.
19. Editing an expense's date to fall inside an active `/profile` range makes it
    appear in the filtered list and tiles; editing it out of the range removes it
    from both. The list and the tiles never disagree about which rows are in scope.
20. The "Recent expenses" card does not appear in either empty state — a new account
    with no expenses still sees "No expenses yet", and a range matching nothing still
    sees "No expenses in this range".
21. `venv/bin/python -m pytest` passes, including the new `tests/test_edit_expense.py`
    **and** `tests/test_add_expense.py` unmodified — the Step 7 tests are the proof
    that extracting the shared validation changed no behaviour. (Note: bare `pytest`
    fails collection — the project root is not on `sys.path`.)
22. `/expenses/1/delete` still returns "Delete expense — coming in Step 9".
23. Every page still renders correctly at a 375px viewport width, with no horizontal
    overflow on the form, the dropdown or the new expense list.
