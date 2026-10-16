PYTHON ?= .venv/bin/python3
PIP ?= .venv/bin/pip
PYTEST ?= .venv/bin/pytest

.PHONY: help install analyze run-pipeline test lint audit serve clean

help:
	@echo "OpsPilot Development Commands:"
	@echo "  make install         Install dependencies and package in editable mode"
	@echo "  make analyze         Run Phase 1 static AST extraction on FILE"
	@echo "  make run-pipeline    Run full OpsPilot modernization pipeline on FILE"
	@echo "  make test            Run test suite"
	@echo "  make lint            Run codebase lint checks (enforces no GroupChat)"
	@echo "  make audit           Run comprehensive architectural, security, and static audits"
	@echo "  make serve           Launch interactive drag-and-drop web modernization interface"
	@echo "  make clean           Clean build and cache artifacts"

install:
	$(PIP) install -e .[dev,extension-plots]

analyze:
	@if [ -z "$(FILE)" ]; then echo "Usage: make analyze FILE=path/to/legacy_file"; exit 1; fi
	PYTHONPATH=src $(PYTHON) -m opspilot.cli analyze "$(FILE)"

run-pipeline:
	@if [ -z "$(FILE)" ]; then echo "Usage: make run-pipeline FILE=path/to/legacy_file"; exit 1; fi
	PYTHONPATH=src $(PYTHON) -m opspilot.cli run-pipeline "$(FILE)"

test:
	PYTHONPATH=src $(PYTEST) -v tests/

lint:
	PYTHONPATH=src $(PYTHON) -c "import pathlib, sys; files = list(pathlib.Path('src').rglob('*.py')); gc = [f for f in files if 'Group' + 'Chat' in f.read_text()]; sys.exit(1) if gc else print('Lint passed: 0 GroupChat occurrences found.')"

audit:
	PYTHONPATH=src $(PYTHON) -m opspilot.cli audit

serve:
	PYTHONPATH=src $(PYTHON) -m opspilot.cli serve --port 8080

clean:
	rm -rf build/ dist/ *.egg-info .pytest_cache workspace/* analysis_output/*
