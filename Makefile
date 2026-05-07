.PHONY: serve test lint format smoke-m2 smoke-m5 backup eval

UV ?= UV_CACHE_DIR=.uv-cache uv run --no-sync

serve:
	$(UV) uvicorn researchmate.api:app --host 127.0.0.1 --port 8000 --workers 1

test:
	$(UV) pytest tests/

lint:
	$(UV) ruff check .
	$(UV) black --check .
	$(UV) mypy

format:
	$(UV) black .
	$(UV) ruff check . --fix

smoke-m2:
	$(UV) python scripts/smoke_test.py --steps 1,2

smoke-m5:
	$(UV) python scripts/smoke_test.py --steps 1,2,3,4,5,6

backup:
	$(UV) python scripts/backup.py

eval:
	$(UV) adk eval eval/agent_module eval/dataset.json --config_file_path eval/config.json
