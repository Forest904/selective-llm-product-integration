PYTHON ?= python
UV_RUN := $(PYTHON) -m uv run

.PHONY: install lint test reproduce dev report report-fixture

install:
	$(PYTHON) -m pip install --upgrade uv
	$(PYTHON) -m uv sync --dev

lint:
	$(UV_RUN) ruff check .
	$(UV_RUN) mypy

test:
	$(UV_RUN) pytest

reproduce:
	$(UV_RUN) mosaic reproduce --fixture

dev:
	$(UV_RUN) mosaic doctor --dev

report:
	$(UV_RUN) mosaic report build

report-fixture:
	$(UV_RUN) mosaic report build --fixture
