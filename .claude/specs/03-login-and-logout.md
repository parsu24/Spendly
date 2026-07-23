# Spec: Login and Logout

## Overview

Step 3 gives Spendly its first sense of *who is signed in*. Registration (Step 2)
writes rows into `users`; this step reads them back. `POST /login` looks up the
account by email, verifies the submitted password against the stored werkzeug
hash, and — on success — records the user's identity in Flask's `session`.
`/logout` clears that session. Because the app now has a notion of an
authenticated visitor, the shared nav learns to render differently for signed-in
users. This is the step that introduces `SECRET_KEY` and `session` to the
project, so every later logged-in feature (the profile page in Step 4, expense
CRUD from Step 7) builds on the session contract established here.

## Depends on

- **Step 1 — Database Setup.** Requires `get_db()` and the `users` table with
  `email` and `password_hash`. Present on `main`.
- **Step 2 — Registration.** Supplies the accounts this step authenticates,
  the lowercase-email normalisation convention, the `.auth-error` /
  `.auth-success` styles, and the `login.html` form that already `POST`s to
  `/login`. Merged to `main`.

## Routes

- `GET /login` — render the sign-in form; if a session is already active,
  redirect to `/` instead of showing the form — public
- `POST /login` — validate credentials, set the session, redirect to `/`; on
  failure re-render `login.html` with a generic `error` and the email still
  filled in — public
- `GET /logout` — clear the session and redirect to `/` — replaces the
  "coming in Step 3" placeholder — public (safe to hit when already logged out)

No other new routes. The `/profile` and `/expenses/*` placeholders stay as they
are.

## Database changes

**No database changes.** The `users` table already holds everything login needs:

| column | why it matters here |
| --- | --- |
| `email` | looked up (lowercased) to find the account |
| `password_hash` | verified with `check_password_hash`, never compared as plain text |
| `id` | stored in the session as the durable identity key |
| `name` | stored in the session for the nav greeting |

## Templates

**Create:** none.

**Modify:**

- `templates/login.html`
  - Repopulate the email field after a failed submit: `value="{{ email or '' }}"`
    on the email input. Never repopulate the password field.
  - The existing `{% if error %}` block and the `registered=1` success notice
    stay exactly as they are.
- `templates/base.html`
  - Make the nav links conditional on `session`:
    - Logged out (`{% if not session.user_id %}`): the current "Sign in" and
      "Get started" links.
    - Logged in: a greeting using `session.name` and a "Log out" link to
      `url_for('logout')`.
  - Flask exposes `session` to Jinja automatically — no route change needed to
    pass it in.

## Files to change

- `app.py`
  - Widen the `flask` import to add `session`.
  - Widen the `werkzeug.security` import to add `check_password_hash`.
  - Set `app.config["SECRET_KEY"]` right after `app = Flask(__name__)`, read
    from `os.environ.get("SECRET_KEY", ...)` with a clearly-labelled dev
    fallback. `session` is unsigned-cookie-unsafe without it.
  - Replace the GET-only `/login` route with `methods=["GET", "POST"]`:
    - GET with an active session → `redirect(url_for("landing"))`.
    - POST: lowercase+strip the email, look the user up via `get_db()`, verify
      with `check_password_hash`, and on success populate the session and
      redirect to `landing`. Close the connection in a `finally`.
  - Replace the `/logout` placeholder body with `session.clear()` followed by
    `redirect(url_for("landing"))`.
- `templates/login.html` — sticky email value (above).
- `templates/base.html` — conditional nav (above).
- `static/css/style.css` — if the logged-in nav needs a greeting style, add a
  `.nav-user` rule beside the existing `.nav-links` / `.nav-cta` block (~line
  95–114) using existing custom properties. Do not restyle the logged-out nav.

## Files to create

- `tests/test_login.py` — covers the Definition of done cases that are cheaper
  to assert than to click through (good/bad credentials, session cookie set and
  cleared, generic error, already-logged-in redirect).

## New dependencies

**No new dependencies.** `werkzeug` is already pinned; `check_password_hash`
ships alongside the `generate_password_hash` the project already uses.

## Rules for implementation

- No SQLAlchemy or ORMs.
- Parameterised queries only — never f-strings or `%` formatting into SQL.
- Verify passwords with `werkzeug.security.check_password_hash` against the
  stored hash. Never `SELECT ... WHERE password_hash = ?` and never compare
  plain text. The submitted password must never reach a log line or a template.
- Normalise the login email the same way registration does: `.strip().lower()`
  before the lookup, so an account registered as `demo@spendly.com` signs in as
  `DEMO@spendly.com` too.
- **One generic failure message** — e.g. "Incorrect email or password." — for
  both an unknown email and a wrong password. Do not reveal which was wrong;
  that distinction leaks which addresses have accounts.
- Store only `session["user_id"]` (and `session["name"]` for the greeting) in
  the session. Do not put the password or hash in the session.
- `SECRET_KEY` must be set before `session` is used. The dev fallback is fine
  for the scaffold but must be commented as not-for-production.
- Query through `get_db()` from `app.py`; close the connection in a `finally`.
  `with get_db() as conn` commits but does not close — the Step 1 docstring
  spells this out.
- Server-side validation regardless of the HTML `required` attributes.
- Use CSS variables — never hardcode hex values. Any new nav rule draws from
  `--ink*` / `--paper*` / `--accent*` like the rest of the sheet.
- All templates extend `base.html`.
- Currency, copy, and tone stay as `CLAUDE.md` describes — INR, "Spendly",
  rupee-oriented.
- Leave the `/profile` and `/expenses/*` placeholders untouched — their
  "coming in Step N" strings are the roadmap.

## Definition of done

Run `python app.py` and visit `http://localhost:5001`:

1. `GET /login` renders the form as before — no regression, and the
   `registered=1` success notice still appears after a fresh registration.
2. Signing in as `demo@spendly.com` / `demo123` (the seeded account) redirects
   to `/`, and the nav now shows the user's name and a "Log out" link instead
   of "Sign in" / "Get started".
3. Signing in with `DEMO@SPENDLY.COM` / `demo123` succeeds too — email case is
   normalised.
4. A wrong password for a real email re-renders `login.html` with the generic
   "Incorrect email or password." message.
5. An email with no account shows the **same** generic message — the wording
   does not distinguish unknown-email from wrong-password.
6. After any failed sign-in the email field is still filled in and the password
   field is empty.
7. Visiting `/logout` clears the session and redirects to `/`; the nav reverts
   to "Sign in" / "Get started".
8. Visiting `/logout` while already logged out is harmless — it redirects to `/`
   without error.
9. Visiting `GET /login` while already signed in redirects to `/` rather than
   showing the form again.
10. The session cookie is signed: with `SECRET_KEY` set, Flask sets a
    `session` cookie on successful login and unsets it on logout.
11. Any new nav styling picks up the site's fonts and colours — no unstyled
    default, no hardcoded hex in the diff.
12. `pytest` passes, including the new `tests/test_login.py` and the existing
    `tests/test_db.py` and `tests/test_register.py`.
13. `git diff` touches only the files listed above.
