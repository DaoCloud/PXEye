PYTHON ?= python3
NODE ?= node
IMAGE ?= pxeye:dev
BASE_IMAGE ?= ubuntu:24.04

.PHONY: syntax lint format-check test wheel image
syntax:
	$(PYTHON) -m compileall -q src tests/unit
	@find src/pxeye/web -name '*.js' -exec $(NODE) --check {} \;
	@find tools -maxdepth 1 -name '*.cjs' -exec $(NODE) --check {} \;

lint:
	$(PYTHON) -m ruff check src tests/unit

format-check:
	npm run format:check

# Optional regression suite: invoke only when explicitly authorized.
test:
	$(PYTHON) -m unittest discover -s tests/unit -t . -p 'test_*.py' -v

wheel:
	$(PYTHON) -m pip wheel --no-deps --wheel-dir dist .

image:
	test -x bin/nico-admin-cli
	test -x bin/grpcurl
	docker build --build-arg BASE_IMAGE=$(BASE_IMAGE) -t $(IMAGE) .
