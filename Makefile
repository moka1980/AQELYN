.PHONY: install lint format typecheck test check up down

install:
	pip install -e ".[dev]"
	pre-commit install

lint:
	ruff check src tests
	ruff format --check src tests

format:
	ruff format src tests

typecheck:
	mypy

test:
	pytest

check: lint typecheck test

up:
	docker compose up -d postgres redis

down:
	docker compose down
