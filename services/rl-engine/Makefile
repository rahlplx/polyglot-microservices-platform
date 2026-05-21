.PHONY: install test lint run docker clean

install:
	pip install -e ".[dev]"

test:
	python -m pytest tests/ -v --cov=src --cov-report=term-missing

lint:
	ruff check src/ tests/
	mypy src/

run:
	python -m src.main

docker:
	docker build -t gstack/rl-engine-service:latest .

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	rm -rf .pytest_cache .mypy_cache .ruff_cache
