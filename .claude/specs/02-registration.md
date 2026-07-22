# Spec: Registration

## Overview

Step 2 turns `/register` from a page that only renders into a route that
actually creates accounts. It accepts the form `register.html` already posts,
validates the three fields, hashes the password with werkzeug, and inserts a
row into the `users` table built in Step 1. On success the visitor is sent to
`/login` with a confirmation notice; on failure the form comes back with an
error message and the fields still filled in. This is the first step that
writes user data, so it is also where the project establishes its habits for
validation, parameterised queries, and duplicate handling — Step 3 (login and
sessions) reads the rows this step writes.

## Depends on

- **Step 1 — Database Setup.** Requires `get_db()`, the `users` table with its
  `UNIQUE` constraint on `email`, and the startup `init_db()` / `seed_db()`
  calls in `app.py`. All present on `main`.

No dependency on sessions: registration does not log the new user in. That is
deliberate — `SECRET_KEY` and `session` belong to Step 3, so this step avoids
`flash()` and signals success with a query parameter instead.

## Routes

- `GET /register` — render the empty registration form — public
- `POST /register` — validate, create the account, redirect to
  `/login?registered=1`; on failure re-render `register.html` with `error` —
  public
- `GET /login` — unchanged, except it now shows a success notice when the
  `registered=1` query parameter is present — public

No other new routes.

## Database changes

**No database changes.** The `users` table already has everything this step
needs:

| column | why it matters here |
| --- | --- |
| `name` | `NOT NULL` — the validation below must reject a blank name |
| `email` | `NOT NULL UNIQUE` — the constraint that makes duplicate detection possible |
| `password_hash` | stores the werkzeug hash, never the password |
| `created_at` | defaults to `datetime('now')` (UTC) — do not set it by hand |

One caveat to handle in code, not schema: SQLite's `UNIQUE` on a `TEXT` column
is case-sensitive, so `Nitish@example.com` and `nitish@example.com` would both
be accepted as separate accounts. Normalise the address to lowercase before
insert so the constraint does the job it looks like it is doing.

## Templates

**Create:** none.

**Modify:**

- `templates/register.html`
  - Repopulate the fields after a failed submit: `value="{{ name or '' }}"` on
    the name input and `value="{{ email or '' }}"` on the email input. Never
    repopulate the password field.
  - Move `autofocus` onto whichever field is in error, or leave it on `name` —
    the existing `{% if error %}` block stays as it is.
- `templates/login.html`
  - Add a success notice above the form, shown only when the redirect from
    registration set the flag:
    ```jinja
    {% if request.args.get('registered') %}
    <div class="auth-success">Account created. Sign in to continue.</div>
    {% endif %}
    ```

## Files to change

- `app.py`
  - Widen the import from `flask` to include `redirect`, `render_template`,
    `request`, and `url_for`.
  - Import `sqlite3` (for `IntegrityError`).
  - `@app.route("/register", methods=["GET", "POST"])` — keep it in the real
    routes section, above `/login`; do not move it into the placeholder block.
  - Drop the `# noqa: F401 (get_db lands in Step 2)` comment on the
    `database.db` import — `get_db` is genuinely used from this step on.
- `templates/register.html` — sticky field values (above).
- `templates/login.html` — success notice (above).
- `static/css/style.css` — add an `.auth-success` rule beside the existing
  `.auth-error` at line ~523, mirroring its shape but in a positive tone. Use
  the existing custom properties only.

## Files to create

- `tests/test_register.py` — covers the cases in Definition of done that are
  cheaper to assert than to click through.

## New dependencies

**No new dependencies.** `werkzeug` is already pinned in `requirements.txt`
and `generate_password_hash` is already imported in `database/db.py`.

## Rules for implementation

- No SQLAlchemy or ORMs.
- Parameterised queries only — never f-strings or `%` formatting into SQL.
- Passwords hashed with `werkzeug.security.generate_password_hash`. The plain
  password must never reach the database, a log line, or a rendered template.
- Use CSS variables — never hardcode hex values. `.auth-success` draws from
  `--ink*` / `--paper*` / `--accent*` like everything else in the sheet.
- All templates extend `base.html`.
- Query through `get_db()` from `app.py`; close the connection in a `finally`.
  `with get_db() as conn` commits but does not close — the Step 1 docstring
  spells this out.
- Validation runs server-side regardless of the HTML `required` attributes;
  those are a convenience, not a control.
- Validation rules, in order, each re-rendering the form with a single
  human-readable `error`:
  1. name, email, password all present after `.strip()`
  2. email contains `@` and a `.` after it
  3. password at least 8 characters (the placeholder already promises this)
  4. email not already registered
- Handle the duplicate email **twice**: a `SELECT` pre-check for the friendly
  message, and a `try/except sqlite3.IntegrityError` around the `INSERT` for
  the race between two simultaneous submits. Both paths show the same error.
  This mirrors the `BEGIN IMMEDIATE` reasoning already in `seed_db()`.
- Store `email` lowercased and `name` stripped. Do not trim the password.
- Currency, copy, and tone stay as they are in `CLAUDE.md` — INR, "Spendly",
  rupee-oriented.
- Leave the `/logout`, `/profile`, and `/expenses/*` placeholders untouched.
  Their "coming in Step N" strings are the roadmap.

## Definition of done

Run `python app.py` and visit `http://localhost:5001`:

1. `GET /register` renders the form as before — no regression.
2. Submitting a valid new name/email/password redirects to `/login` and the
   page shows "Account created. Sign in to continue."
3. `sqlite3 spendly.db "SELECT name, email, password_hash FROM users"` shows
   the new row, the email lowercased, and a `password_hash` that starts with
   a werkzeug algorithm prefix (e.g. `scrypt:` or `pbkdf2:`) — not the
   password.
4. Submitting the same email a second time re-renders the form with a
   duplicate-email error, and the users table still holds exactly one such row.
5. Submitting `demo@spendly.com` (the seeded account) is rejected the same way.
6. Submitting `DEMO@SPENDLY.COM` is rejected too — case is normalised.
7. A password of 7 characters is rejected with a length error; 8 is accepted.
8. An email of `notanemail` is rejected with a format error.
9. After any rejection the name and email fields are still filled in and the
   password field is empty.
10. The error and success notices both pick up the site's fonts and colours —
    no unstyled browser default, no hardcoded hex in the diff.
11. `pytest` passes, including the new `tests/test_register.py` and the
    existing `tests/test_db.py`.
12. `git diff` touches only the files listed above.
