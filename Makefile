# Any Python >= 3.11 works (tested: 3.11, 3.12, 3.13, 3.14).
# Pick one with PYTHON=python3.12 or PYTHON="$(uv python find 3.12)".
PYTHON        ?= python3
VENV          ?= .venv
BIN           := $(VENV)/bin
# Where to install the MCP server from: a local checkout (default) or a pip
# URL such as "git+https://github.com/<owner>/mcp-logistica@<sha>".
MCP_LOGISTICA ?= ../mcp-logistica
CONSTRAINTS   ?= constraints.txt
DB            ?= data/wms.sqlite
EVALSET       ?= evals/wms_assistant.test.json
EVAL_CONFIG   ?= evals/test_config.json

# Agent settings. Make exports them ONLY when you pass them on the command line
# (make run POLICY=dry_run DB=other.sqlite). Otherwise the agent reads
# WMS_WRITE_POLICY / WMS_DB_PATH from your shell or from .env, and falls back
# to off and data/wms.sqlite. (An exported variable beats .env in ADK.)
ifeq ($(origin POLICY),command line)
export WMS_WRITE_POLICY := $(POLICY)
endif
ifeq ($(origin DB),command line)
export WMS_DB_PATH := $(abspath $(DB))
endif

.PHONY: help install seed test lint typecheck format check run web eval eval-offline clean

help:  ## list targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | sed 's/:.*## /\t/'

install:  ## .venv + mcp-logistica + this package with dev tools, at the tested versions
	@$(PYTHON) -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else "Python >= 3.11 required. Try: make install PYTHON=python3.12")'
	@case "$(MCP_LOGISTICA)" in \
		git+*|http://*|https://*) ;; \
		*) if [ ! -d "$(MCP_LOGISTICA)" ]; then \
			echo "mcp-logistica not found at '$(MCP_LOGISTICA)'."; \
			echo "Clone it next to this repository:"; \
			echo "  git clone https://github.com/noelaliaga/mcp-logistica ../mcp-logistica"; \
			echo "or point MCP_LOGISTICA at a checkout or a git+https URL."; \
			exit 2; fi ;; \
	esac
	$(PYTHON) -m venv $(VENV)
	$(BIN)/python -m pip install --upgrade pip
	@if [ -d "$(MCP_LOGISTICA)" ]; then \
		echo "$(BIN)/python -m pip install -c $(CONSTRAINTS) -e $(MCP_LOGISTICA)"; \
		$(BIN)/python -m pip install -c $(CONSTRAINTS) -e "$(MCP_LOGISTICA)"; \
	else \
		echo "$(BIN)/python -m pip install -c $(CONSTRAINTS) 'mcp-logistica @ $(MCP_LOGISTICA)'"; \
		$(BIN)/python -m pip install -c $(CONSTRAINTS) "mcp-logistica @ $(MCP_LOGISTICA)"; \
	fi
	$(BIN)/python -m pip install -c $(CONSTRAINTS) -e '.[dev]'

seed:  ## (re)create the synthetic WMS database at $(DB) with mcp-logistica's seed
	$(BIN)/wms-seed --db $(DB) --force

test:  ## offline: scripted model, real MCP server, no network, no keys
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

eval-offline:  ## ADK's evaluator on the eval set with a replayed agent: no keys, no network
	@echo "Offline replay: checks the eval files, tool names and metric wiring, NOT model quality."
	@echo "An 'MCP session' / ConnectionError traceback after the results is expected (ADK 2.9.1 re-lists tools after closing its runners)."
	PYTHONPATH=tests:agents WMS_MCP_TIMEOUT_S=5 WMS_WRITE_POLICY=off WMS_DB_PATH=$(abspath $(DB)) \
		$(BIN)/adk eval tests/offline_agents/replay $(EVALSET) --config_file_path evals/offline_config.json --print_detailed_results

run:  ## chat in the terminal. Needs model credentials (see .env.example). POLICY=off|dry_run|on
	$(BIN)/adk run agents/wms_assistant

web:  ## ADK dev UI on http://127.0.0.1:8000. Opens without keys, answers only with them
	$(BIN)/adk web agents

eval:  ## ADK eval with YOUR keys: paid calls to the agent model and the Gemini judge
	@echo "adk eval calls the configured model and a Gemini judge model with your credentials."
	$(BIN)/adk eval agents/wms_assistant $(EVALSET) --config_file_path $(EVAL_CONFIG) --print_detailed_results

clean:
	rm -rf .mypy_cache .pytest_cache .ruff_cache build dist agents/*.egg-info
