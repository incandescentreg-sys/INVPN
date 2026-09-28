# =============================================================================
#  Makefile — типовые команды разработки
# =============================================================================

SHELL := /bin/bash
BACKEND := backend
WEBAPP := webapp
VENV := $(BACKEND)/.venv
PY := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
NPM := npm --prefix $(WEBAPP)

.DEFAULT_GOAL := help
.PHONY: help install install-backend install-webapp dev dev-api dev-web worker \
        test test-backend lint typecheck format migrate migration revision \
        smoke build build-webapp up down logs shell clean

help: ## Показать доступные команды
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

# ---------------------------------------------------------------- install ----
install: install-backend install-webapp ## Установить все зависимости

install-backend: ## venv + pip зависимости
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r $(BACKEND)/requirements-dev.txt

install-webapp: ## npm зависимости
	$(NPM) install

# -------------------------------------------------------------------- run ----
dev: ## Локально: API и Web App одновременно
	@echo "API  -> http://127.0.0.1:8000/docs"
	@echo "Web -> http://127.0.0.1:5173"
	@trap 'kill 0' EXIT; \
	 (cd $(BACKEND) && ../$(PY) -m uvicorn app.main:app --reload --port 8000) & \
	 $(NPM) run dev & \
	 wait

dev-api: ## Только API с автоперезагрузкой
	cd $(BACKEND) && ../$(PY) -m uvicorn app.main:app --reload --port 8000

dev-webapp: ## Только Web App
	$(NPM) run dev

worker: ## Фоновые задачи (для self-hosted)
	cd $(BACKEND) && ../$(PY) -m app.workers.scheduler

# ----------------------------------------------------------------- tests ----
test: test-backend ## Прогнать все тесты

test-backend: ## pytest
	cd $(BACKEND) && ../$(PY) -m pytest -q

smoke: ## Быстрая проверка API в процессе
	cd $(BACKEND) && ../$(PY) scripts/smoke.py

# ------------------------------------------------------------------ lint ----
lint: ## ruff + tsc
	cd $(BACKEND) && ../$(PY) -m ruff check app tests
	$(NPM) run typecheck

typecheck: ## Только типы фронтенда
	$(NPM) run typecheck

format: ## Автоформатирование
	cd $(BACKEND) && ../$(PY) -m ruff format app tests && ../$(PY) -m ruff check --fix app tests

# ----------------------------------------------------------------- db -------
migrate: ## Применить миграции
	cd $(BACKEND) && ../$(PY) -m alembic upgrade head

migration: ## Новая миграция: make migration m="описание"
	cd $(BACKEND) && ../$(PY) -m alembic revision --autogenerate -m "$(m)"

revision: ## Откатить последнюю миграцию
	cd $(BACKEND) && ../$(PY) -m alembic downgrade -1

# ---------------------------------------------------------------- docker ----
build: build-webapp ## Собрать образы

build-webapp: ## Собрать фронтенд
	$(NPM) run build

up: ## docker compose up
	docker compose up -d --build

down: ## Остановить
	docker compose down

logs: ## Логи сервисов
	docker compose logs -f --tail=100

shell: ## Shell внутри API-контейнера
	docker compose exec api bash

clean: ## Удалить кэши и артефакты
	find . -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
	rm -rf $(BACKEND)/.pytest_cache $(WEBAPP)/dist $(WEBAPP)/node_modules/.vite
