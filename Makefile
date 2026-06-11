PYTHON ?= python
UV_RUN := $(PYTHON) -m uv run

.PHONY: install lint test reproduce dev report report-fixture clean-generated clean-generated-yes deterministic-scale

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

clean-generated:
	$(UV_RUN) mosaic maintenance clean-generated

clean-generated-yes:
	$(UV_RUN) mosaic maintenance clean-generated --yes

deterministic-scale:
	$(UV_RUN) mosaic experiment deterministic-scale
