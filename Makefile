PYTHON ?= python3
NODE ?= node
VERSION = $(shell $(PYTHON) -c 'import tomllib; print(tomllib.load(open("pyproject.toml", "rb"))["project"]["version"])')
BUILD_TIME := $(shell TZ=Asia/Shanghai date +%Y%m%d%H%M)
IMAGE ?= mmzhou-os-install-console:$(VERSION)-$(BUILD_TIME)
VCS_REF := $(shell git rev-parse HEAD)
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
	@if test -n "$$(git status --porcelain --untracked-files=normal)"; then echo "Commit changes and use a clean working tree before building" >&2; exit 1; fi
	@if docker image inspect "$(IMAGE)" >/dev/null 2>&1; then echo "Image already exists: $(IMAGE); use a new build minute/tag" >&2; exit 1; fi
	test -x bin/nico-admin-cli
	test -x bin/grpcurl
	test -x bin/helm
	docker build --build-arg BASE_IMAGE="$(BASE_IMAGE)" --build-arg VCS_REF="$(VCS_REF)" --build-arg VERSION="$(VERSION)" -t "$(IMAGE)" .
	@echo "BUILT_IMAGE=$(IMAGE)"
