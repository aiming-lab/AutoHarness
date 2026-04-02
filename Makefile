.PHONY: test lint format typecheck install dev clean

test:
	python -m pytest tests/ -q

test-verbose:
	python -m pytest tests/ -v

lint:
	ruff check src/ tests/

format:
	ruff format src/ tests/

typecheck:
	mypy src/harnessagent --ignore-missing-imports

install:
	pip install -e .

dev:
	pip install -e ".[dev]"

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type d -name .pytest_cache -exec rm -rf {} +
	rm -rf dist/ build/ *.egg-info

examples:
	@echo "Running all examples..."
	@for f in examples/*.py; do echo "\n=== $$f ===" && python "$$f" || true; done
