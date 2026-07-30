SERVICE  := festival-service
IMAGE    := arcadia/$(SERVICE)
VERSION  ?= local
VENV     := .venv
PY       := $(VENV)/bin/python

.DEFAULT_GOAL := help
.PHONY: help install test cover lint fmt run docker clean

help: 
	@grep -hE '^[a-zA-Z0-9_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

install:
	python3 -m venv $(VENV)
	$(PY) -m pip install --quiet --upgrade pip
	$(PY) -m pip install --quiet -e '.[dev]'
	@echo "installed"

test: 
	$(PY) -m pytest -q

cover: 
	$(PY) -m pytest --cov=app --cov-report=term-missing

lint: 
	$(VENV)/bin/ruff check .
	$(VENV)/bin/ruff format --check .

fmt: 
	$(VENV)/bin/ruff format .
	$(VENV)/bin/ruff check --fix .

run: 
	$(VENV)/bin/uvicorn app.main:app --reload --port 8091

docker: 
	docker build --build-arg VERSION=$(VERSION) -t $(IMAGE):$(VERSION) .
	@echo "built $(IMAGE):$(VERSION)"

clean: 
	rm -rf $(VENV) .pytest_cache .ruff_cache
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
