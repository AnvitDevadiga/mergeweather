PY ?= python3

.PHONY: demo test clean
demo:
	$(PY) scripts/demo.py

test:
	$(PY) -m pytest -q

clean:
	rm -rf build demo-output .pytest_cache
