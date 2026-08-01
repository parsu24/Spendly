# Spec: Delete Expense

## Overview

Step 8 made an existing row editable and, in doing so, established the pattern this
step completes: a value from the URL names a database record, and the only thing
between it and somebody else's data is a `WHERE id = ? AND user_id = ?`. Step 9
finishes expense CRUD by making a row removable. The new lesson is not ownership —
that was Step 8's — it is **method discipline around a destructive action**: the
placeholder at `app.py:1079-1081` is a bare `GET`, and a delete that fires on `GET`
fires on a link prefetch, a passing crawler or a browser restoring tabs, with nobody
having clicked anything. `profile_delete()` already carries this reasoning
(`app.py:634-642`); this step applies the same GET-confirm / POST-destroy shape to a
single row. Once it lands, the "Placeholder routes" banner in `app.py` holds nothing
and comes out with it, and every expense in the "Your expenses" list Step 8 added is
reachable for both editing and removal.

## Depends on

- **Step 1 — Database Setup.** Requires `get_db()`, the `expenses` table
  (`database/db.py:63-71`) and `format_inr` / the `inr` filter (`app.py:21`).
  Present on `main`.
- **Step 3 — Login and Logout.** Supplies `session["user_id"]`, the second half of
  every `WHERE` clause here. Merged to `main`.
- **Step 4 — Profile Page Design.** Supplies `/profile`, the page this route
  redirects back to. Merged to `main`.
- **Step 5 — Account Management.** Supplies the destructive-action vocabulary this
  step reuses wholesale: the GET-confirmation / POST-destroy route shape
  (`app.py:596-693`), `templates/profile_delete.html` as the model for the
  confirmation screen, `.profile-danger`, `.btn-danger`, `.profile-form-card`,
  `.profile-form-actions`, and the `?updated=1` / `?password=1` success-notice
  pattern that `?deleted=1` joins. Merged to `main`.
- **Step 6 — Date Filter.** Supplies the `clause` / `params` construction in
  `profile()` (`app.py:278-286`). Not modified here, but the redirect target is a
  filtered page and the checklist below tests what a delete looks like under an
  active range. Merged to `main`.
- **Step 7 — Add Expense.** Supplies `AMOUNT_MAX`, `DESCRIPTION_MAX` and
  `parse_expense_form()`. **None of them are used by this step** — a delete submits
  no fields — and none of them may be touched. Merged to `main` as `641054b`.
- **Step 8 — Edit Expense.** Supplies everything this step extends: the
  ownership-scoped `SELECT … WHERE id = ? AND user_id = ?` shape
  (`app.py:990-1001`), the stale-cookie check, the "Your expenses" list on
  `/profile` (`templates/profile.html:134-149`), and the `.profile-expense-*` grid
  in `static/css/style.css:738-801` plus its mobile stacking rules. Merged to `main`
  as `b674f96` (PR #9).

The seeded demo account (`demo@spendly.com` / `demo123`) makes this verifiable end
to end: it holds eight expenses totalling `₹18,240`, so deleting the `₹3,450`
groceries row is visible as `7` and `₹14,790` on `/profile` the moment the redirect
lands.

## Routes

- `GET /expenses/<int:id>/delete` — render a confirmation screen naming the expense,
  and **delete nothing**; **404** if that id is not this account's — **logged-in only**
- `POST /expenses/<int:id>/delete` — `DELETE` that one row, then redirect to
  `/profile?deleted=1`; **404** on the same condition — **logged-in only**

Both replace the placeholder at `app.py:1079-1081`
(`"Delete expense — coming in Step 9"`). The route keeps its existing URL rule and
its existing function name `delete_expense` — `url_for('delete_expense', id=...)` is
the only way templates should build the link. The rule gains
`methods=["GET", "POST"]`; today it is `GET`-only by omission.

**The route moves** out from under the "Placeholder routes" banner into the
"Expenses" section, below `edit_expense()`, so the three expense routes read in the
order they were built. The banner comment block at `app.py:1074-1076` then has
nothing under it and is **deleted entirely** — a section header labelling an empty
section is worse than no header. This is the last stub; there is no Step 10 route
waiting to inherit it.

**No new list route** and no bulk delete. One row, one id, one confirmation.

**404, not 403, for an id that is not yours**, and the same 404 for an id that never
existed — the reasoning `profile()` carries at `app.py:262-267` and `edit_expense()`
repeats at `app.py:996-1001`. `abort(404)` is already imported (`app.py:6`).

## Database changes

**No database changes.** This step adds no table, no column, no constraint and no
index. `SCHEMA` in `database/db.py:54-72` must not be touched — the `CREATE TABLE`
statements are `IF NOT EXISTS`, so any edit would silently do nothing on a developer
database that already exists.

Specifically:

- **A hard `DELETE`, not a soft one.** No `deleted_at` column, no `is_deleted` flag,
  no archive table, no trash view. A soft delete changes the meaning of every query
  written in Steps 4-8 — each would need `AND deleted_at IS NULL` bolted on, and the
  first one that forgot would quietly resurrect the row in a total. That is a real
  design, but it is not this one, and retrofitting it is not a beginner step.
- `expenses.id` — the `INTEGER PRIMARY KEY` the URL names; used only inside a
  `WHERE` that also names `user_id`.
- `expenses.user_id` — appears in the `WHERE` clause of both statements and nowhere
  else.
- **Nothing cascades from here.** `expenses` is a leaf: `ON DELETE CASCADE` is
  declared on `expenses.user_id` pointing *at* `users` (`database/db.py:65`), so
  deleting a user removes expenses, not the reverse. Deleting one expense affects
  exactly one row. Do not add a `PRAGMA` or a second statement "to be safe".
- **The account's other rows and the account itself are untouched.** This route must
  never `DELETE FROM users`, and it must never delete more than one row — no
  `DELETE … WHERE user_id = ?` without an `id`, ever, in this route or its tests.

Note the column is named `date` and `app.py` imports `date` from `datetime`
(`app.py:4`). Do not shadow that import with a local variable named `date`.

## Templates

**Create:**

- `templates/expense_delete.html` — extends `base.html`, `{% block title %}` reads
  "Delete expense — Spendly". Modelled on `profile_delete.html`, which is the
  project's existing confirmation screen, and following the project's one-template-
  per-page convention:
  - `h1.profile-name` reads "Delete this expense"; a `p.profile-meta` line says what
    is about to happen.
  - a `.profile-danger` box naming the row in full — its amount through the `inr`
    filter, its category, its date in the page's `format_day()` voice, and its
    description (or an em dash when `NULL`). This is what makes the action
    recoverable in practice: everything needed to re-enter the expense is on the
    screen before it is destroyed, which is the whole reason this route asks for no
    password. Follow it with the plain sentence "This cannot be undone."
  - `<form method="POST" action="{{ url_for('delete_expense', id=id) }}">` — the id
    travels in the **URL only**. No hidden `<input name="id">`, no hidden `user_id`;
    carry the comment `expense_edit.html:17-19` carries, adapted.
  - the form's only controls are a `button.btn-danger` reading "Delete expense" and
    a `.btn-ghost` Cancel link back to `/profile`, inside `.profile-form-actions` —
    the same pairing `profile_delete.html:46-51` uses, with the destructive control
    wearing `--danger` so the safe choice is the easy one.
  - **no password field** and no `{% if error %}` block: this form has no input, so
    there is no submission it can reject. Do not copy those parts of
    `profile_delete.html` in.

**Modify:**

- `templates/profile.html` —
  - add an `{% if request.args.get('deleted') %}` `.auth-success` notice ("Your
    expense has been deleted.") as a **fifth sibling** of the four at lines 11-30,
    not an `{% elif %}` — the existing comments there explain why.
  - in the "Your expenses" list (lines 134-149), add a **Delete** link beside the
    existing Edit link on each row, pointing at
    `url_for('delete_expense', id=expense.id)`. It is a link to the confirmation
    screen, not a form button — the destruction happens on the POST that screen
    sends, so a plain `<a>` here is correct and stays consistent with Edit.
  - the two empty states keep their current copy unchanged.

`base.html` needs **no change**. `expense_add.html` and `expense_edit.html` need
**no change** — in particular, do not add a delete control to the edit form. One
destructive path, reachable from the list.

## Files to change

- `app.py` —
  - implement `delete_expense(id)` in the "Expenses" section, below
    `edit_expense()`, with `methods=["GET", "POST"]`.
  - delete the stub at lines 1079-1081 and the now-empty "Placeholder routes"
    banner at lines 1074-1076.
  - the route body, in this order: session guard → `get_db()` → stale-cookie check →
    ownership-scoped `SELECT` → `abort(404)` if `None` → on `GET`, render the
    confirmation → on `POST`, `DELETE … WHERE id = ? AND user_id = ?`, `commit()`,
    redirect. `finally: conn.close()`.
  - the `SELECT` reads `amount`, `category`, `date` and `description` because the
    confirmation screen names the row; it needs nothing else. Render the date through
    the existing `format_day()` helper (`app.py:193-199`) so this page speaks about
    dates the way `/profile` does — pass the formatted string to the template rather
    than formatting in Jinja.
  - leave `profile()`, `parse_expense_form()`, `add_expense()`, `edit_expense()`,
    `parse_range()` and every account route **untouched**. The `/profile` list query
    already selects `id` (`app.py:327-332`) and the `expenses` dict already carries
    it (`app.py:354-363`), so the new link needs no route change at all.
- `templates/profile.html` — the two changes listed above.
- `static/css/style.css` — in the existing `/* Profile page */` section
  (`:636-906`), beside the `.profile-expense-*` rules at `:738-801`:
  - widen `.profile-expense-row`'s `grid-template-columns` (`:745`) to carry a sixth
    track for the delete link, keeping the note on the `1fr`.
  - add `.profile-expense-delete`, built like `.profile-expense-edit` (`:795-801`)
    but coloured `var(--danger)`, matching `.profile-danger-link a` (`:972`).
  - **update the mobile block.** `@media (max-width: 600px)` explicitly places every
    cell of this row by `grid-area` (`.profile-expense-edit { grid-area: 2 / 2; }`
    and its siblings); a sixth column added without a matching rule there lands the
    delete link wherever the browser puts it. Give the two links a shared cell or
    their own row — whichever holds at 375px.
  - no new top-level section, no new colour literals.
- `CLAUDE.md` — the Architecture bullet for `app.py` still describes
  `/logout`, `/profile` and `/expenses/...` as placeholder routes returning "coming
  in Step N" strings. After this step no route in the file does. Correct that
  sentence; change nothing else in the file.

## Files to create

- `templates/expense_delete.html` — described above.
- `tests/test_delete_expense.py` — the method, ownership and blast-radius cases from
  the Definition of done, following the fixture style in
  `tests/test_edit_expense.py` (whose `login` / `register` / `add` helpers are worth
  mirroring). `tests/conftest.py` already redirects `SPENDLY_DB` at a scratch file,
  so no new fixture plumbing is needed.

## New dependencies

**No new dependencies.** A delete needs no parsing and no validation library —
`<int:id>` in the URL rule is the only conversion involved, and Werkzeug does it.
Do not add Flask-WTF for a CSRF token on this form alone, and do not add a JS
confirm library. `static/js/main.js` stays untouched.

## Rules for implementation

- **No SQLAlchemy or ORMs.** Raw `sqlite3` through `get_db()`, as in Steps 2-8.
- **Parameterised queries only.** The `SELECT` and the `DELETE` bind every value as
  a `?` placeholder — never an f-string, never `%` formatting, never `.format()`.
  There is no dynamic clause to build on this route at all.
- **`GET` must not delete anything.** The confirmation is rendered on `GET`; the row
  is destroyed only on `POST`. Branch on `request.method` the way
  `profile_delete()` does (`app.py:634-642`), and make sure nothing before that
  branch writes. This is the single most important rule in this spec: a destructive
  `GET` fires on a prefetch, a crawler or a restored tab with nobody having clicked.
  It is also why the stub's bare `@app.route(...)` must gain an explicit
  `methods=["GET", "POST"]`.
- **Ownership is enforced in the `WHERE` clause of every statement, not in Python.**
  Both the `SELECT` that loads the row and the `DELETE` that removes it carry
  `WHERE id = ? AND user_id = ?` with `user_id` from the session. Do not fetch by id
  alone and compare `row["user_id"]` afterwards, and do not rely on the earlier
  `SELECT` to make the `DELETE` safe — the statement that writes must be safe on its
  own, exactly as `edit_expense()`'s `UPDATE` is (`app.py:1039-1042`).
- **`abort(404)` when the `SELECT` returns nothing**, on both `GET` and `POST`, for
  both a nonexistent id and another account's id. Never 403, never a redirect, never
  a message distinguishing the two.
- **Apply the login guard first**, before the row is looked up and before
  `request.form` is read. Copy the shape from `edit_expense()` (`app.py:970-972`).
  It must guard the `POST` as well as the `GET`. A logged-out request must get the
  login redirect and **not** a 404, so the route never reveals whether an id exists
  to someone who is not signed in.
- **`user_id` comes from the session, never from the form or the URL.** No hidden
  `user_id` field, no `?user=` parameter. The `id` in the path names a row; it does
  not name an owner.
- **No password re-authentication on this route**, and this is a deliberate
  asymmetry, not an omission — record it in a comment the way `profile_edit()` does
  (`app.py:404-409`). `/profile/delete` asks for the password because it destroys an
  account and everything in it, irreversibly. This destroys one row whose every
  field is displayed on the confirmation screen immediately before it goes, so
  re-entering it costs one form. The GET confirmation *is* the guard here.
- **Exactly one row, exactly once.** The `DELETE` names an `id`. Never
  `DELETE FROM expenses WHERE user_id = ?` alone, never `DELETE FROM users`, and no
  second statement cleaning up after it — `expenses` is a leaf table.
- **Close the connection in a `finally`.** `with get_db() as conn` commits but does
  not close (see the `get_db()` docstring); every route in `app.py` closes by hand
  and carries the same comment. `conn.commit()` after the `DELETE` — a delete that
  is never committed is the quietest possible failure.
- **Handle the stale-cookie case** the way every logged-in route does: if the
  account behind the session no longer exists, `session.clear()` and redirect to
  `login`. The ownership-scoped `SELECT` would 404 for a deleted account — correct
  but useless — so check the user first, as `edit_expense()` does
  (`app.py:980-984`).
- **Redirect on success, to `url_for("profile", deleted=1)`.** Not
  `render_template`, not back to the confirmation. A POST that answers with HTML
  leaves the delete sitting in the browser's history. Do not attach range parameters
  to the redirect — `?edited=1` and `?added=1` do not either.
- **A second POST to the same id after the row is gone must 404, not 500.** The
  `SELECT` returns nothing and `abort(404)` handles it; that is the correct answer
  and it needs no special case. Make sure the `abort` precedes anything that would
  touch the missing row.
- **Escaping is Jinja's job and it is already doing it.** The description is
  attacker-controlled text and this step renders it in a second place — the
  confirmation screen. Render it as `{{ description }}` and do not reach for `|safe`
  anywhere.
- **Use CSS variables — never hardcode hex values.** `--ink*` / `--paper*` /
  `--accent*` / `--danger*` / `--border*` / `--radius-*` / `--font-*`. The delete
  link and the confirmation box are built from the existing variables and the
  existing `.profile-card` / `.profile-danger` boxes.
- **Reuse the existing vocabulary** — `.profile-card`, `.profile-danger`,
  `.profile-form-card`, `.profile-form-actions`, `.btn-danger`, `.btn-ghost`,
  `.auth-success`, `.profile-expense-row` and its siblings — rather than inventing
  parallel classes. `.profile-expense-delete` is the only new selector, and it is
  named in the established `.profile-*` style.
- **All templates extend `base.html`** and use its `{% block %}` slots. No second
  `<nav>` or `<footer>`.
- **No JavaScript.** No `onclick="return confirm(...)"`, no fetch-based delete, no
  row that disappears without a page load. The confirmation screen is the confirm
  dialog, and it works with JS off — which is the point of it being a page.
- Currency stays **INR** — the amount on the confirmation screen and every amount in
  the list goes through the `inr` filter, and no `$` or `USD` appears anywhere.
- **CSRF protection is out of scope**, consistently with every other form in the
  project. Do not add a token to this form alone.
- **Passwords hashed with werkzeug** — unchanged; this step touches no credential
  code.
- Existing behaviour must not regress: `?updated=1`, `?password=1`, `?added=1` and
  `?edited=1` keep working, Step 6's filter still applies on `/profile`,
  `/expenses/add` and `/expenses/<id>/edit` behave exactly as before, and
  `tests/test_add_expense.py` and `tests/test_edit_expense.py` pass **unmodified**.
- The confirmation screen and the widened list row must render correctly at a
  **375px** viewport width with no horizontal overflow. Verify rather than assume.

## Definition of done

Run `python app.py` and visit `http://localhost:5001`, signed in as
`demo@spendly.com` / `demo123`. Baseline: 8 expenses, `₹18,240`.

1. Each row of the "Your expenses" card on `/profile` shows a **Delete** link beside
   its Edit link, and the link is visibly distinct from Edit (it wears `--danger`).
2. Clicking **Delete** opens `/expenses/<id>/delete` and shows a confirmation naming
   that exact row — its amount in `₹` with Indian grouping, its category, its date
   and its description — with a "Delete expense" button and a Cancel link.
3. **The `GET` deletes nothing.** After loading the confirmation screen and *not*
   submitting, `/profile` still shows 8 expenses and `₹18,240`. Confirm the row is
   still present:
   `sqlite3 spendly.db "SELECT COUNT(*) FROM expenses WHERE id = 1"` returns `1`.
4. Clicking **Cancel** returns to `/profile` with the row still present and no
   success notice shown.
5. Confirming the delete of the `₹3,450` groceries row redirects to
   `/profile?deleted=1`, shows "Your expense has been deleted.", and the tiles move
   to **7** expenses and **₹14,790**. The row is gone from the list.
6. Deleting the account's only row in a category removes that category's bar from
   "Where your money goes" entirely, and the remaining bar widths redraw.
7. A row whose `description` is `NULL` renders a dash or similar placeholder on the
   confirmation screen — not the word "None", not an empty gap, and no traceback.
8. Refreshing after the post-success redirect does not re-submit the delete and
   produces no error — the URL is `/profile?deleted=1`, not the delete route.
9. **Re-submitting a completed delete 404s.** Use the browser's back button to the
   confirmation screen of the row just deleted and submit again: the response is
   404, not a 500 and not a second success notice.
10. **Ownership.** Register a second account, add an expense to it, then — signed in
    as the demo user — `GET /expenses/<that id>/delete` returns **404**, and `POST`
    to it returns 404 and leaves the other account's row **present**. Confirm the
    row directly in the database, not just by the status code.
11. `GET /expenses/99999/delete` (an id that has never existed) returns 404, the
    same response as the previous case.
12. Logged out, `GET /expenses/1/delete` redirects to `/login` — **not** 404 — and
    `POST /expenses/1/delete` also redirects to `/login` and deletes nothing.
    Confirm the row is still in the database afterwards.
13. `POST /expenses/<own id>/delete` carrying an extra `user_id=2` field deletes
    only the row named in the URL and leaves the other account's rows untouched.
14. **Blast radius.** Before and after deleting one row, check
    `sqlite3 spendly.db "SELECT COUNT(*) FROM expenses"` across *all* accounts: the
    count drops by exactly 1. `SELECT COUNT(*) FROM users` is unchanged, and the
    signed-in session is still valid — deleting an expense must not sign anyone out.
15. Deleting an expense while a date range is active on `/profile` lands back on the
    unfiltered page with the notice shown, and the deleted row is absent from both
    the tiles and the list under any range.
16. Deleting the last remaining expense on an account shows the first-run empty
    state ("No expenses yet"), not the filtered one, and the "Your expenses" card
    does not render at all.
17. A description containing `'); DROP TABLE expenses; --` renders escaped on the
    confirmation screen rather than as markup, and deleting that row leaves the
    schema and every other row intact.
18. `/expenses/<id>/edit` still works exactly as it did — open the edit form for a
    surviving row, save it unchanged, and confirm the redirect and the row.
19. `venv/bin/python -m pytest` passes, including the new
    `tests/test_delete_expense.py` **and** `tests/test_add_expense.py` and
    `tests/test_edit_expense.py` unmodified. (Note: bare `pytest` fails collection —
    the project root is not on `sys.path`.)
20. `grep -n "coming in Step" app.py` returns nothing, and the "Placeholder routes"
    banner is gone from the file.
21. Every page still renders correctly at a 375px viewport width, with no horizontal
    overflow on the confirmation screen or on the expense list row now carrying two
    links.
