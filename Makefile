.PHONY: install demo test lint format typecheck check build clean css
install:
	uv venv --allow-existing && uv pip install -e '.[dev]'

demo: install
	.venv/bin/mergeweather demo

test: install
	.venv/bin/pytest -q

lint:
	.venv/bin/ruff check .
	.venv/bin/ruff format --check .

format:
	.venv/bin/ruff check --fix .
	.venv/bin/ruff format .

typecheck:
	.venv/bin/mypy

check: lint typecheck test

build:
	uv build

clean:
	rm -rf build dist .venv mergeweather-demo mergeweather-report .pytest_cache

css:
	npx --yes tailwindcss@3.4.17 -c tools/tailwind.config.js -i tools/tailwind.in.css -o src/mergeweather/assets/report.css --minify
