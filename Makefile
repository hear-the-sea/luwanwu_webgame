PYTHON ?= python3
MANAGE ?= $(PYTHON) manage.py
LOCAL_STATE_DIR ?= .local
FLAKE8_TARGETS ?= accounts battle gameplay guests guilds trade core websocket config tests
MYPY_TARGETS ?= accounts battle common config core gameplay guests guilds tasks trade websocket

.PHONY: install install-unpinned install-lock install-dev-lock migrate bootstrap-data dev dev-ws worker beat test test-unit test-critical test-integration test-all format lint lint-strict check clean lock lock-dev

install:
	@if [ -f requirements-dev.lock.txt ]; then \
		pip install -r requirements-dev.lock.txt; \
	elif [ -f requirements.lock.txt ]; then \
		pip install -r requirements.lock.txt -r requirements-dev.txt; \
	else \
		pip install -r requirements-dev.txt; \
	fi

install-unpinned:
	pip install -r requirements-dev.txt

install-lock:
	pip install -r requirements.lock.txt

install-dev-lock:
	pip install -r requirements-dev.lock.txt

lock:
	$(PYTHON) scripts/generate_requirements_lock.py requirements.txt > requirements.lock.txt

lock-dev:
	$(PYTHON) scripts/generate_requirements_lock.py requirements-dev.txt > requirements-dev.lock.txt

precommit:
	pre-commit install

migrate:
	$(MANAGE) migrate

bootstrap-data:
	$(MANAGE) bootstrap_game_data --skip-images

# 传统 HTTP 开发服务器（不支持 WebSocket）
dev:
	$(MANAGE) runserver 0.0.0.0:8000

# ASGI 开发服务器（支持 WebSocket）
dev-ws:
	daphne -b 0.0.0.0 -p 8000 config.asgi:application

worker:
	celery -A config worker -l info

beat:
	mkdir -p $(LOCAL_STATE_DIR)
	celery -A config beat -l info --schedule $(LOCAL_STATE_DIR)/celerybeat-schedule

# Default to the hermetic unit-like suite, then surface critical concurrency coverage explicitly.
test: test-unit test-critical

test-unit:
	$(PYTHON) -m pytest -m "not integration"

test-critical:
	@if [ "$$DJANGO_TEST_USE_ENV_SERVICES" = "1" ]; then \
		$(PYTHON) -m pytest tests/test_raid_concurrency_integration.py tests/test_work_service_concurrency.py -q; \
	else \
		echo "Skipping critical concurrency integration tests; set DJANGO_TEST_USE_ENV_SERVICES=1 to enable non-SQLite verification."; \
	fi

test-integration:
	DJANGO_TEST_USE_ENV_SERVICES=1 $(PYTHON) -m pytest -m integration -q

test-all:
	$(PYTHON) -m pytest

cov:
	$(PYTHON) -m coverage run -m pytest
	$(PYTHON) -m coverage report -m

cov-html:
	$(PYTHON) -m coverage run -m pytest
	$(PYTHON) -m coverage html
	@echo "Open htmlcov/index.html"

# Code formatting and linting
format:
	black .
	isort .

lint:
	$(PYTHON) -m flake8 --jobs=1 $(FLAKE8_TARGETS)
	@$(PYTHON) -m mypy --version >/dev/null 2>&1 || { echo "mypy is required for lint. Run: make install"; exit 1; }
	$(PYTHON) -m mypy $(MYPY_TARGETS)

lint-strict:
	$(PYTHON) -m flake8 --jobs=1 $(FLAKE8_TARGETS)
	$(PYTHON) -m mypy $(MYPY_TARGETS)

check: format lint
	@echo "Code formatting and linting completed!"

clean:
	rm -rf $(LOCAL_STATE_DIR) .pytest_cache .ruff_cache .mypy_cache htmlcov
	find . -type d -name "__pycache__" -prune -exec rm -rf {} +
	find . -type f -name "*.py[cod]" -delete
