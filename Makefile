.PHONY: install demo test build clean css
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

css:
	npx --yes tailwindcss@3.4.17 -c tools/tailwind.config.js -i tools/tailwind.in.css -o src/mergeweather/assets/report.css --minify
