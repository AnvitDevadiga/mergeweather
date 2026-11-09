.PHONY: install demo test build clean
install:
	uv venv --allow-existing && uv pip install -e '.[dev]'

demo: install
	.venv/bin/mergeweather demo

test: install
	.venv/bin/pytest -q

build:
	uv build

clean:
	rm -rf build dist .venv mergeweather-demo mergeweather-report .pytest_cache
