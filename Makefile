PYTHON ?= python3
NODE ?= node
REPO_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
VERSION = $(shell $(PYTHON) -c 'import tomllib; print(tomllib.load(open("$(REPO_ROOT)/pyproject.toml", "rb"))["project"]["version"])')
BUILD_TIME := $(shell TZ=Asia/Shanghai date +%Y%m%d%H%M)
IMAGE ?= mmzhou-os-install-console:$(VERSION)-$(BUILD_TIME)
VCS_REF := $(shell git -C "$(REPO_ROOT)" rev-parse HEAD)
BASE_IMAGE ?= ubuntu:24.04
OFFLINE_BUILD_CONFIG ?= build-config.json
OFFLINE_BUNDLE_VERSION ?=
OFFLINE_DELIVERY := $(REPO_ROOT)/offline-build/delivery.py
OFFLINE_VERSION_ARG := $(if $(OFFLINE_BUNDLE_VERSION),--version $(OFFLINE_BUNDLE_VERSION),)

.PHONY: syntax lint format-check test wheel image bundles
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

# Build a complete offline delivery from the locked PXEye parent Chart.
# The cache-seed command is idempotent: it exports local containerd images only
# when the Chart-derived closure changes; otherwise it returns immediately.
bundles:
	@test -f "$(OFFLINE_BUILD_CONFIG)" || { echo "Missing OFFLINE_BUILD_CONFIG=$(OFFLINE_BUILD_CONFIG)" >&2; exit 1; }
	$(PYTHON) "$(OFFLINE_DELIVERY)" --config "$(OFFLINE_BUILD_CONFIG)" --seed-cache
	$(PYTHON) "$(OFFLINE_DELIVERY)" --config "$(OFFLINE_BUILD_CONFIG)" $(OFFLINE_VERSION_ARG)
