# Repository Guidelines

## Project Structure

- `config/`: Django project config (`settings.py`, `urls.py`, `asgi.py`, `celery.py`).
- App modules live at repo root (e.g. `accounts/`, `battle/`, `guests/`, `guilds/`, `trade/`, `websocket/`).
- `templates/`: Django templates (server-rendered HTML).
- `static/` and `media/`: static assets and user-uploaded/generated files.
- `data/`: YAML-driven game templates (e.g. `data/guest_templates.yaml`, `data/*_templates.yaml`).
- `tests/`: pytest suite (Django-enabled via `pytest-django`).
- `docs/`: deeper architecture/development notes (see `docs/index.md`).

## Build, Test, and Development Commands

Common workflows are captured in `Makefile`:

- `make install`: install Python deps from `requirements.txt`.
- `make migrate`: apply database migrations.
- `make dev`: run Django dev server (HTTP only) on `0.0.0.0:8000`.
- `make dev-ws`: run ASGI server (WebSocket-capable) via `daphne`.
- `make worker` / `make beat`: run Celery worker / scheduler (requires Redis).
- `make test`: run `pytest`.
- `make format`: run `black` + `isort`.
- `make lint`: run `flake8` + `mypy`.

Docker (MySQL + Redis + web/worker/beat):

- `docker compose up --build`

## Coding Style & Naming Conventions

- Python: Black + isort (`line-length = 120`, isort profile `black`); keep imports sorted.
- Lint/type checks: `flake8` and `mypy` (see `pyproject.toml` for exact config).
- Django conventions: models/classes in `PascalCase`, functions/vars in `snake_case`, constants in `UPPER_SNAKE_CASE`.

## Testing Guidelines

- Framework: `pytest` + `pytest-django` (`DJANGO_SETTINGS_MODULE=config.settings`).
- Naming: place tests in `tests/test_*.py` (also matches `test_*.py` and `*_tests.py`).
- Run: `make test` (add focused runs like `pytest tests/test_battle.py -k retreat`).

## Commit & Pull Request Guidelines

- Existing history uses short, imperative subjects (e.g. “Add …”). Keep commits focused and descriptive.
- PRs should include: what/why, how to verify (commands + expected result), and screenshots for UI changes.
- If you change YAML templates in `data/`, note any required management commands (e.g. `python manage.py load_guest_templates`) and include relevant tests/fixtures.

