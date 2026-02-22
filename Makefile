PYTHON ?= python3
MANAGE ?= $(PYTHON) manage.py
LOCAL_STATE_DIR ?= .local
FLAKE8_TARGETS ?= accounts battle gameplay guests guilds trade core websocket config tests
MYPY_TARGETS ?= accounts battle common config core gameplay guests guilds tasks trade websocket

.PHONY: install migrate dev dev-ws worker beat test test-integration format lint lint-strict check clean

install:
	pip install -r requirements-dev.txt

install-lock:
	pip install -r requirements.lock.txt

lock:
	$(PYTHON) scripts/generate_requirements_lock.py > requirements.lock.txt

precommit:
	pre-commit install

migrate:
	$(MANAGE) migrate

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

test:
	$(PYTHON) -m pytest

test-integration:
	DJANGO_TEST_USE_ENV_SERVICES=1 $(PYTHON) -m pytest -m integration -q

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
	@$(PYTHON) -c "import mypy" >/dev/null 2>&1 || { echo "mypy is not installed; skipping type check. Run: make install"; exit 0; }; $(PYTHON) -m mypy $(MYPY_TARGETS)

lint-strict:
	$(PYTHON) -m flake8 --jobs=1 $(FLAKE8_TARGETS)
	$(PYTHON) -m mypy $(MYPY_TARGETS)

check: format lint
	@echo "Code formatting and linting completed!"

clean:
	rm -rf $(LOCAL_STATE_DIR) .pytest_cache .ruff_cache .mypy_cache htmlcov
	find . -type d -name "__pycache__" -prune -exec rm -rf {} +
	find . -type f -name "*.py[cod]" -delete
