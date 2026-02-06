PYTHON ?= python3
MANAGE ?= $(PYTHON) manage.py
LOCAL_STATE_DIR ?= .local
FLAKE8_TARGETS ?= accounts battle gameplay guests guilds trade core websocket config tests

.PHONY: install migrate dev dev-ws worker beat test format lint check clean

install:
	pip install -r requirements-dev.txt

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

# Code formatting and linting
format:
	black .
	isort .

lint:
	$(PYTHON) -m flake8 --jobs=1 $(FLAKE8_TARGETS)
	$(PYTHON) -m mypy .

check: format lint
	@echo "Code formatting and linting completed!"

clean:
	rm -rf $(LOCAL_STATE_DIR) .pytest_cache .ruff_cache .mypy_cache htmlcov
	find . -type d -name "__pycache__" -prune -exec rm -rf {} +
	find . -type f -name "*.py[cod]" -delete
