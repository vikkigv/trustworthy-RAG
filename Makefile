.PHONY: install dev test lint format compose-up compose-down worker migrate revision

migrate:
	uv run alembic upgrade head

revision:
	uv run alembic revision --autogenerate -m "$(m)"

install:
	uv sync --extra dev

dev:
	uv run uvicorn api.main:app --reload --port 8000

test:
	uv run pytest -q

lint:
	uv run ruff check .
	uv run mypy trust_rag api

format:
	uv run ruff format .

compose-up:
	docker compose up -d --build

compose-down:
	docker compose down

worker:
	uv run arq trust_rag.worker.WorkerSettings
