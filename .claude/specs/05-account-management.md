# Spec: Account Management

## Overview

Step 4 gave a signed-in user a page that is theirs, but it is strictly
read-only — it renders `users` and `expenses` and never writes a row. Step 5
adds the write side of the account: changing your name and email, changing your
password, and deleting your account outright. It is the first step where a
logged-in user **mutates** data, so it is where the project establishes the
habits that expense CRUD (Steps 7–9) will repeat: a form that re-renders itself
with an error and the fields still filled in, an `UPDATE` scoped to
`session["user_id"]` and never to anything the visitor can type, a re-auth gate
in front of the dangerous operations, and a destructive action that lives behind
a `POST` and a confirmation screen. No new tables — every column this step
touches already exists.

## Depends on

- **Step 1 — Database Setup.** Requires `get_db()`, the `users` table, and — for
  account deletion — the `ON DELETE CASCADE` on `expenses.user_id` together with
  the `PRAGMA foreign_keys = ON` that `get_db()` sets per connection
  (`database/db.py:65`, `:115`). Present on `main`.
- **Step 2 — Registration.** Supplies the validation vocabulary this step
  mirrors: lowercase email normalisation, the "never strip a password" rule, the
  `EMAIL_TAKEN` message, the `SELECT`-then-catch-`IntegrityError` pattern, and
  the `.auth-error` / `.form-group` / `.form-input` / `.btn-submit` styles.
  Merged to `main`.
- **Step 3 — Login and Logout.** Supplies `SECRET_KEY`, `session["user_id"]`,
  `session["name"]`, `check_password_hash` usage, and `session.clear()` — which
  deletion reuses verbatim. Merged to `main`.
- **Step 4 — Profile Page Design.** Supplies `GET /profile`, the login-required
  guard this step copies onto six new routes, and the `.profile-*` CSS section
  (`static/css/style.css:605-725`) the new screens extend. Merged to `main`.

The seeded demo account (`demo@spendly.com` / `demo123`) is what makes every
flow here clickable without registering first. Note that deleting it means
re-seeding — `seed_db()` only inserts when `users` is empty, so removing the
last user makes the next start re-seed automatically.

## Routes

- `GET /profile/edit` — render the edit form pre-filled with the current name
  and email — **logged-in only**
- `POST /profile/edit` — validate, `UPDATE users` , refresh `session["name"]`,
  redirect to `/profile`; on failure re-render with `error` — **logged-in only**
- `GET /profile/password` — render the change-password form — **logged-in only**
- `POST /profile/password` — verify the current password, hash and store the new
  one, redirect to `/profile`; on failure re-render with `error` — **logged-in
  only**
- `GET /profile/delete` — render the confirmation screen, stating plainly how
  many expenses will go with the account — **logged-in only**
- `POST /profile/delete` — verify the password, delete the user, clear the
  session, redirect to `/` — **logged-in only**

Each pair is one Flask route with `methods=["GET", "POST"]`, matching how
`/register` (`app.py:49`) and `/login` (`app.py:116`) are already written. An
anonymous visitor to any of the six is redirected to `GET /login`, exactly as
`/profile` does.

The `/expenses/*` placeholders keep their "coming in Step N" strings.

## Database changes

**No database changes.** Every column this step writes already exists in
`database/db.py:55-61`:

- `users.name` — updated by `/profile/edit`
- `users.email` — updated by `/profile/edit`; its `UNIQUE` constraint is what
  makes the duplicate check enforceable rather than advisory
- `users.password_hash` — rewritten by `/profile/password`
- `users.id` — the `DELETE` target; `expenses.user_id REFERENCES users(id) ON
  DELETE CASCADE` (`database/db.py:65`) removes that user's expenses in the same
  statement

`users.created_at` is never rewritten — "Member since" must survive an edit.

No migration is needed and `SCHEMA` must not be touched. Do not add an
`updated_at` column; it would require deleting `spendly.db` to take effect,
since the `CREATE TABLE` statements are `IF NOT EXISTS`.

## Templates

**Create:**

- `templates/profile_edit.html` — name and email fields, Save + Cancel
- `templates/profile_password.html` — current, new, confirm-new fields
- `templates/profile_delete.html` — the confirmation screen: what is about to be
  destroyed, a password field, a destructive submit and a Cancel

**Modify:**

- `templates/profile.html` — add an actions row under `.profile-header` linking
  to `/profile/edit` and `/profile/password`, and a quieter "Delete account"
  link to `/profile/delete` placed at the foot of the page, away from the
  everyday controls. Add a `{% if success %}` notice slot using the existing
  `.auth-success` style so a completed edit confirms itself.

`base.html` needs **no change** — the nav already links to `/profile`
(`templates/base.html:23`), and these are sub-pages reached from there.

## Files to change

- `app.py` — three new routes in the real-routes section, placed immediately
  after `/profile` and before the `/terms` route so the profile group reads as
  one block. Import `check_password_hash` is already there (`app.py:6`); nothing
  new to import. Leave the "Placeholder routes" banner and its three stubs
  exactly as they are.
- `templates/profile.html` — the action links and success notice above.
- `static/css/style.css` — extend the existing `/* Profile page */` section
  (`:605-725`) with `.profile-actions`, `.profile-form-card`,
  `.profile-danger` and `.btn-danger`. Do not open a new top-level section and
  do not touch the Auth section.
- `README.md` — **only if it exists**; it does not at time of writing, so skip.

## Files to create

- `templates/profile_edit.html`
- `templates/profile_password.html`
- `templates/profile_delete.html`
- `tests/test_account.py` — the access-control, validation and cascade cases
  from the Definition of done, following the `monkeypatch.setattr(db,
  "DB_PATH", ...)` fixture in `tests/test_profile.py:10-22`

## New dependencies

**No new dependencies.** Flask, Jinja2, `sqlite3` and `werkzeug.security` cover
all of it, and all are already in `requirements.txt`.

## Rules for implementation

- **No SQLAlchemy or ORMs.** Raw `sqlite3` through `get_db()`, as in Steps 2–4.
- **Parameterised queries only** — never f-strings or `%` formatting into SQL.
- **Passwords hashed with werkzeug.** `generate_password_hash` for the new
  password, `check_password_hash` to verify the current one. Never compare a
  password in SQL, never log one, never put one in a template context, and never
  `.strip()` one.
- **Every write is scoped by `WHERE id = ?` against `session["user_id"]`.**
  There is no `/profile/<id>/edit` form of any of these routes. A route that
  takes an id from the URL or a hidden form field is a bug even when it happens
  to work for the demo account.
- Apply the same guard `/profile` uses (`app.py:158-160`): read `user_id` from
  the session, redirect to `login` when it is missing. On `POST` too — the guard
  must run before any form parsing, since anything can POST directly to these
  URLs.
- **Re-authenticate before the dangerous operations.** Both
  `POST /profile/password` and `POST /profile/delete` require the account's
  current password in the form and must reject on a failed
  `check_password_hash`. `POST /profile/edit` deliberately does **not** — name
  and email are recoverable changes, and the extra friction is not worth it at
  this stage. Write that trade-off down in a comment rather than leaving the
  asymmetry to look like an oversight.
- **Normalise email the way Step 2 does** — `.strip().lower()` — so an account
  registered as `demo@spendly.com` cannot be edited into `Demo@Spendly.com` and
  become a second distinct address under SQLite's case-sensitive `TEXT`
  comparison.
- **The duplicate-email check must exclude your own row:**
  `SELECT id FROM users WHERE email = ? AND id != ?`. Without the second
  clause, saving the form without changing the email reports "already exists"
  against yourself. Keep the `try/except sqlite3.IntegrityError` around the
  `UPDATE` as well, for the same race Step 2 documents (`app.py:100-106`), and
  reuse the existing `EMAIL_TAKEN` constant rather than writing a new string.
- **Refresh `session["name"]` after a successful name change.** The nav renders
  `session.name` (`templates/base.html:23`), so skipping this leaves the old
  name in the header until the next login — the single most likely bug in this
  step.
- Re-validate everything the templates mark `required`: non-empty name, a
  plausible email, and the **same minimum-8-character rule** registration
  enforces (`app.py:83`). The new password must also match its confirmation
  field, and rejecting a new password identical to the current one is a nice
  touch, not a requirement.
- **Destructive actions happen on `POST` only.** `GET /profile/delete` renders
  the confirmation and must not delete anything — a link prefetch or a crawler
  hitting a `GET` delete would be catastrophic. This is also why the existing
  `/expenses/<id>/delete` placeholder gets revisited in Step 9, not here.
- Deletion runs a single `DELETE FROM users WHERE id = ?` and lets
  `ON DELETE CASCADE` remove the expenses. Do **not** delete from `expenses`
  by hand — the point of the exercise is that the schema already guarantees it.
  Verify `PRAGMA foreign_keys = ON` is in force; without it SQLite silently
  ignores the rule and orphans every row.
- Follow the delete with `session.clear()` before redirecting, so no cookie
  survives pointing at an id that no longer exists.
- `conn.commit()` after every write, and close the connection in a `finally`.
  `with get_db() as conn` commits but does not close — the Step 1 docstring
  (`database/db.py:103-112`) spells this out.
- Re-render failures with the submitted values still in place, minus any
  password field, following `reject()` in `app.py:66-72`.
- **Use CSS variables — never hardcode hex values.** The destructive styling
  uses the existing `--danger` and `--danger-light` (`static/css/style.css:17-18`);
  everything else comes from `--ink*` / `--paper*` / `--accent*` / `--radius-*`
  / `--font-*`. No new colour literals anywhere.
- Reuse the existing form vocabulary — `.form-group`, `.form-input`,
  `.btn-submit`, `.auth-error`, `.auth-success` — rather than inventing parallel
  classes. **Cancel links use `.btn-ghost`** (`static/css/style.css:342-358`),
  which is defined but currently unused by any template; this step is what
  finally consumes it. New selectors are namespaced `.profile-*`.
- **All templates extend `base.html`** and use its `{% block %}` slots. No
  second `<nav>` or `<footer>`.
- Copy stays in the project's voice: "Spendly", plain sentences, rupee-oriented.
  The delete screen states the real consequence — how many expenses and what
  total are about to be destroyed — with amounts through the `inr` filter, never
  `$` or `USD`.
- The new screens must be responsive, collapsing like the existing profile
  layout does at 900px.

## Definition of done

Run `python app.py` and visit `http://localhost:5001`:

1. Visiting `/profile/edit`, `/profile/password` or `/profile/delete` while
   **logged out** redirects to `/login` — for both `GET` and a direct `POST`,
   with no traceback and no data leaked.
2. Signed in as `demo@spendly.com` / `demo123`, `/profile` shows working links
   to edit, change password, and delete.
3. `/profile/edit` renders with the name and email already filled in.
4. Changing the name to `Demo Owner` and saving redirects to `/profile`, which
   shows `Demo Owner` — **and the nav in the header shows it too, without
   logging out and back in.**
5. Saving the edit form without changing the email succeeds — it does not report
   the address as already taken.
6. Registering a second account, then trying to edit the demo account's email to
   that address, re-renders the form with the "already exists" error and leaves
   the database unchanged.
7. Submitting an empty name, a malformed email, or a blank field re-renders with
   a specific error and the other fields still filled in.
8. `/profile/password` with a **wrong** current password re-renders with an
   error, and the old password still works on `/login`.
9. `/profile/password` with a correct current password and matching new
   passwords redirects to `/profile`; logging out then signing in with the
   **new** password succeeds and the old one fails.
10. A new password under 8 characters, or one that does not match its
    confirmation, is rejected with a clear message.
11. `/profile/delete` shows a confirmation screen naming the number of expenses
    and their total in rupees (`₹18,240` for the untouched demo account) — and
    loading that page deletes nothing.
12. Submitting the delete form with a wrong password re-renders with an error
    and the account still exists.
13. Submitting it with the correct password redirects to `/`, leaves the nav in
    its signed-out state, and `/profile` afterwards redirects to `/login`.
14. After a delete, `sqlite3 spendly.db "SELECT COUNT(*) FROM expenses"` returns
    `0` — the cascade removed the expenses, and no orphan rows remain.
15. `venv/bin/python -m pytest` passes, including the new `tests/test_account.py`.
    (Note: bare `pytest` currently fails collection — the project root is not on
    `sys.path`.)
16. Every page still renders correctly at a 375px viewport width.
