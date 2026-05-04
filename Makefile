.PHONY: serve test lint format smoke-m2

serve:
	uv run uvicorn researchmate.api:app --host 127.0.0.1 --port 8000 --workers 1

test:
	uv run pytest tests/

lint:
	uv run ruff check .
	uv run black --check .
	uv run mypy

format:
	uv run black .
	uv run ruff check . --fix

smoke-m2:
	uv run python scripts/smoke_test.py --steps 1,2
