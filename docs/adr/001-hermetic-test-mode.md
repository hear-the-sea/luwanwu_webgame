# ADR-001: Use hermetic test mode as default

## Status: Accepted
## Date: 2026-03

## Context

The project depends on several external services at runtime: PostgreSQL (or another
RDBMS), Redis (cache, channel layer, Celery broker), and Celery workers.  Requiring
all of these for every `pytest` invocation creates friction for daily development,
slows CI feedback, and introduces flaky failures caused by network or service state.

The settings package (`config/settings/__init__.py`) detects `RUNNING_TESTS` and,
unless the developer explicitly opts in via `DJANGO_TEST_USE_ENV_SERVICES=1`,
applies `config/settings/testing.py` which replaces every external dependency with
an in-process equivalent:

| Concern        | Production             | Hermetic test mode          |
|----------------|------------------------|-----------------------------|
| Database       | PostgreSQL             | SQLite (per-worker tmpfile) |
| Cache          | django-redis           | LocMemCache                 |
| Channel layer  | channels_redis         | InMemoryChannelLayer        |
| Celery broker  | Redis                  | `memory://`                 |
| Celery backend | Redis                  | `cache+memory://`           |

Health-check flags for Celery and Channel Layer are also disabled so that the test
suite never reaches out to infrastructure it does not control.

## Decision

Use hermetic, zero-dependency test defaults.  A single `pytest` command must work
on a fresh checkout with nothing but Python installed.  Developers who need to
verify real-infrastructure behavior opt in with `DJANGO_TEST_USE_ENV_SERVICES=1`.

SQLite test databases are placed in the OS temp directory with a worker-ID and PID
suffix to support `pytest-xdist` parallelism without file collisions.

## Consequences

- **Positive:** Fast feedback loop; no Docker/Redis/Postgres required for most tests;
  deterministic execution; trivial CI setup.
- **Negative:** `select_for_update()` is a no-op on SQLite, so concurrent locking
  logic is not exercised by default.  Redis Lua scripts, pub/sub, and real Channels
  group routing are not tested.  Celery task serialisation round-trips are skipped
  when eager mode is enabled.
- **Mitigation:** Integration tests that exercise these paths should run in a
  separate CI stage with `DJANGO_TEST_USE_ENV_SERVICES=1` and real services.
