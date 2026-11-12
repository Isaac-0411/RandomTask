# RandomTask

A small daily task planner built with Flask. Each account gets a randomly sized
list of 2–9 tasks every day, fills in whatever matters to them, and checks items
off as they go. Progress is saved per account and kept day by day.

## Features

- **Accounts** — register, sign in, and sign out with hashed passwords and
  server-side sessions.
- **A daily draw** — 2–9 blank task slots per user, allocated once per day and
  kept stable across page refreshes.
- **Autosave** — task text and completion state are saved through a small JSON
  endpoint as you edit. Blank tasks cannot be marked complete, and clearing a
  task's text resets its completion.
- **Progress view** — a live completion ring, counts, filters, and a daily
  summary.
- **History** — every day on record with its completed tasks, total wins, and
  fully completed days.
- **Avatars** — choose a male, female, or initial-based avatar.
- **Time zone aware days** — the current day is calculated in a configurable
  time zone (default `Asia/Bangkok`), not the server's local clock.
- **Health check** — `GET`/`HEAD /health` returns `{"status":"ok"}` without
  touching the database, for uptime monitors and hosting platforms.
- **Themes** — light and dark mode are remembered in the browser.

## Tech stack

- Python 3.9+ (uses `zoneinfo`)
- Flask 3
- Flask-SQLAlchemy / SQLAlchemy
- SQLite by default, or any SQL database via `DATABASE_URL`
- Gunicorn for production
- Plain HTML, CSS, and JavaScript templates — no frontend build step

## Project structure

```
.
├── app.py                  # Flask app, models, routes, and startup logic
├── requirements.txt        # Python dependencies
├── render.yaml             # Render.com deployment blueprint
├── templates/              # Jinja templates (auth, dashboard, history)
├── static/
│   ├── css/style.css       # Styling and light/dark themes
│   └── js/main.js          # Autosave, filters, progress, avatar menu, theme
├── tests/test_app.py       # Behavioral tests
├── fanpage/                # Separate side project bundled in this repo
└── fanpage-keepalive.patch # Patch related to the fanpage project
```

## Getting started

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Open <http://127.0.0.1:5000>. The database is created automatically on startup
at `instance/randomtask.db` when no `DATABASE_URL` is set.

For development with the reloader:

```bash
FLASK_DEBUG=1 python app.py
# or
flask --app app run --debug
```

## Configuration

Configuration is read from environment variables:

| Variable        | Default                    | Purpose                                                        |
| --------------- | -------------------------- | -------------------------------------------------------------- |
| `SECRET_KEY`    | generated and persisted    | Session signing key. If unset, a random key is written to `instance/.secret_key`. |
| `DATABASE_URL`  | `sqlite:///randomtask.db`  | SQLAlchemy database URL.                                       |
| `APP_TIMEZONE`  | `Asia/Bangkok`             | Time zone used to decide what "today" means.                   |
| `FLASK_DEBUG`   | unset                      | Set to `1` to run the development server with debug enabled.   |

Generate a strong key for production, for example:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

## Routes

| Method      | Path           | Description                                              |
| ----------- | -------------- | -------------------------------------------------------- |
| `GET`       | `/`            | Redirects to the dashboard or login page.                |
| `GET/POST`  | `/register`    | Create an account (username 3–80 chars, password 4–128). |
| `GET/POST`  | `/login`       | Sign in.                                                 |
| `GET`       | `/logout`      | Clear the session and return to login.                   |
| `GET`       | `/dashboard`   | Today's tasks and progress.                              |
| `POST`      | `/update_task` | JSON endpoint to save task text and/or completion.       |
| `GET`       | `/history`     | Completed tasks grouped by day.                          |
| `POST`      | `/profile`     | JSON endpoint to change the avatar.                      |
| `GET/HEAD`  | `/health`      | Lightweight health check, no database access.            |

Example task update:

```bash
curl -X POST http://127.0.0.1:5000/update_task \
  -H 'Content-Type: application/json' \
  -b cookies.txt \
  -d '{"task_id": 1, "content": "Take a walk", "completed": true}'
```

Task text is limited to 1000 characters. Invalid or unauthenticated requests get
a JSON `error` response with an appropriate `4xx` status.

## Data model

- `User` — username, hashed password, avatar preference.
- `DailyTask` — one row per user per date, holding that day's task count. A
  unique index on `(user_id, date)` prevents duplicate daily allocations.
- `Task` — task text and completion state, belonging to a `DailyTask`.

Tables and the daily uniqueness index are created automatically at startup.
Existing databases are upgraded in place.

## Running tests

```bash
python -m unittest discover -s tests -v
```

The tests use an in-memory SQLite database and cover registration and login,
account isolation, input validation, autosave behavior, daily allocation,
time-zone boundaries, history counts, avatars, and the health endpoint.

## Deployment

`render.yaml` defines a Render web service that:

- installs `requirements.txt`,
- starts with `gunicorn app:app`,
- checks `/health`,
- generates `SECRET_KEY`,
- sets `APP_TIMEZONE` to `Asia/Bangkok`.

Set `DATABASE_URL` to a persistent database in production. SQLite on an
ephemeral filesystem will not survive a redeploy or restart.

To run the production server manually:

```bash
gunicorn app:app
```

## Notes

- The `fanpage/` directory is an unrelated side project and has its own
  `README.md`.
- This README covers the Flask application in the repository root.
