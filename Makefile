.PHONY: install dev test testv lint format typecheck check fix clean

install:
	pip install -e ".[dev]"

dev:
	uvicorn northbound.main:app --reload --host 0.0.0.0 --port 1211

test:
	pytest

testv:
	pytest -v

lint:
	ruff check src tests

format:
	ruff format src tests

typecheck:
	pyright 

check: lint typecheck format

fix:
	ruff check --fix src tests
	make check

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	rm -rf .ruff_cache .pytest_cache

