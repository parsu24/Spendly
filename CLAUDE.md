# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

"Spendly" — a Flask expense-tracker **teaching scaffold**. The landing/auth/legal pages and the full CSS design system are built, but the app's core (database, authentication, expense CRUD) is intentionally left as stubs for students to implement in numbered steps. When editing, preserve this progression: the route comments (e.g. `# coming in Step 3`) and `database/db.py`'s docstring describe what each step must build.

## Commands

Use the project virtualenv at `venv/`.

```bash
source venv/bin/activate           # or prefix commands with venv/bin/
python app.py                      # run dev server at http://localhost:5001 (debug=True)
pytest                             # run tests (pytest + pytest-flask are installed)
pytest path/to/test_file.py::test_name   # run a single test
pip install -r requirements.txt    # install deps
```

Note: the server runs on **port 5001**, not the Flask default 5000.

## Architecture

- **`app.py`** — the entire Flask application: one `app = Flask(__name__)` and all route definitions, grouped by section-comment banners. Every route is now implemented — no "coming in Step N" placeholders remain — covering the landing/legal pages, registration and login, the account routes under `/profile`, and expense add/edit/delete under `/expenses`.
- **`database/db.py`** — SQLite data layer (built in Step 1). `get_db()` returns a connection with `row_factory` and foreign keys enabled; `init_db()` creates tables with `CREATE TABLE IF NOT EXISTS`; `seed_db()` inserts dev sample data. Both are called from `app.py` inside `app.app_context()` on startup, so the DB file — `spendly.db` in the project root, gitignored — is created automatically. `CATEGORIES` is the fixed category list; later dropdowns should read from it. No ORM, parameterized queries only.
- **`templates/`** — Jinja2. All pages `{% extends "base.html" %}`; `base.html` provides the nav, footer, and `{% block title/head/content/scripts %}` slots. Auth templates already expect an `error` variable and POST to their own routes.
- **`static/css/style.css`** — the design system (~650 lines). Everything is driven by CSS custom properties in `:root` (`--ink*`, `--paper*`, `--accent*`, fonts, radii). Reuse these variables and existing component classes rather than adding ad-hoc styles; fonts are DM Serif Display (display) and DM Sans (body).
- **`static/js/main.js`** — near-empty; client-side behavior gets added here as features are built.

## Conventions

- Match the existing style: routes grouped by section-comment banners in `app.py`, semantic component classes in templates, CSS variables for all theming values.
- The brand name throughout the UI is "Spendly"; the copy is rupee-oriented ("Track every rupee").
- Currency is **INR, not USD**. Format amounts with the `₹` symbol and Indian digit grouping (e.g. `₹18,240`) — never `$` or `USD`. This applies to UI copy, seed/sample data, and any new templates or JS.
