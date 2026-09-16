PYTHON        ?= python3
VENV          ?= .venv
BIN           := $(VENV)/bin
# Where to install the MCP server from: a local checkout (default) or a pip
# requirement such as "git+https://github.com/<owner>/mcp-logistica@<ref>".
MCP_LOGISTICA ?= ../mcp-logistica
DB            ?= data/wms.sqlite
POLICY        ?= off
EVALSET       ?= evals/wms_assistant.test.json
EVAL_CONFIG   ?= evals/test_config.json

export WMS_DB_PATH := $(abspath $(DB))
export WMS_WRITE_POLICY := $(POLICY)

.PHONY: install seed test lint typecheck format check run web eval clean

install:  ## .venv + mcp-logistica + this package with dev tools (PYTHON=python3.12 to pick one)
	@$(PYTHON) -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else "Python >= 3.11 required. Try: make install PYTHON=python3.12")'
	$(PYTHON) -m venv $(VENV)
	$(BIN)/python -m pip install --upgrade pip
	@if [ -d "$(MCP_LOGISTICA)" ]; then \
		$(BIN)/python -m pip install -e "$(MCP_LOGISTICA)"; \
	else \
		$(BIN)/python -m pip install "mcp-logistica @ $(MCP_LOGISTICA)"; \
	fi
	$(BIN)/python -m pip install -e '.[dev]'

seed:  ## (re)create the synthetic WMS database at $(DB) with mcp-logistica's seed
	$(BIN)/wms-seed --db $(DB) --force

test:  ## offline: no model calls, no network
	$(BIN)/pytest

lint:  ## ruff + ruff format --check + mypy --strict
	$(BIN)/ruff check .
	$(BIN)/ruff format --check .
	$(BIN)/mypy

typecheck:
	$(BIN)/mypy

format:
	$(BIN)/ruff format .
	$(BIN)/ruff check --fix .

check: lint test

run:  ## chat in the terminal. Needs model credentials (see .env.example). POLICY=off|dry_run|on
	$(BIN)/adk run agents/wms_assistant

web:  ## ADK dev UI on http://127.0.0.1:8000. Needs model credentials. POLICY=off|dry_run|on
	$(BIN)/adk web agents

eval:  ## ADK eval with YOUR keys: paid calls to the agent model and the judge model
	@echo "adk eval calls the configured model and a judge model with your credentials."
	$(BIN)/adk eval agents/wms_assistant $(EVALSET) --config_file_path $(EVAL_CONFIG) --print_detailed_results

clean:
	rm -rf .mypy_cache .pytest_cache .ruff_cache build dist agents/*.egg-info
