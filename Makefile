PYTHON ?= python3
NODE ?= node
REPO_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
VERSION = $(shell $(PYTHON) -c 'import tomllib; print(tomllib.load(open("$(REPO_ROOT)/pyproject.toml", "rb"))["project"]["version"])')
BUILD_TIME := $(shell TZ=Asia/Shanghai date +%Y%m%d%H%M)
IMAGE ?= mmzhou-os-install-console:$(VERSION)-$(BUILD_TIME)
VCS_REF := $(shell git -C "$(REPO_ROOT)" rev-parse HEAD)
BASE_IMAGE ?= ubuntu:24.04
BUILD_CONFIG ?= $(REPO_ROOT)/../build-config.json
BUILD_WORK_DIRECTORY ?= $(REPO_ROOT)/../outputs_
BUNDLE_VERSION ?= bundle-$(VERSION)-$(shell TZ=Asia/Shanghai date +%Y%m%d%H%M)
DELIVERY_SCRIPT := $(REPO_ROOT)/offline-build/delivery.py
VERSION_ARG := $(if $(BUNDLE_VERSION),--version $(BUNDLE_VERSION),)

.PHONY: syntax lint format-check test wheel image cache-images bundles
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
# Defaults: a build-config.json and outputs_ directory beside this checkout,
# and a PXEye-versioned Asia/Shanghai timestamped bundle version. Override only for a separate workspace
# or a repeatable output version.
bundles:
	@if test ! -f "$(BUILD_CONFIG)"; then \
		echo "INITIALIZE_BUILD_CONFIG $(BUILD_CONFIG)"; \
		$(PYTHON) "$(DELIVERY_SCRIPT)" --write-config "$(BUILD_CONFIG)" --work-directory "$(BUILD_WORK_DIRECTORY)"; \
	fi
	@test -f "$(BUILD_CONFIG)" || { echo "Missing BUILD_CONFIG=$(BUILD_CONFIG)" >&2; exit 1; }
	@test -n "$(REGISTRY)" || { echo "Set REGISTRY=host:port" >&2; exit 1; }
	REGISTRY="$(REGISTRY)" REGISTRY_INSECURE="$(REGISTRY_INSECURE)" $(PYTHON) "$(DELIVERY_SCRIPT)" --config "$(BUILD_CONFIG)" $(VERSION_ARG)

cache-images:
	@test -n "$(REGISTRY)" || { echo "Set REGISTRY=host:port" >&2; exit 1; }
	REGISTRY="$(REGISTRY)" REGISTRY_INSECURE="$(REGISTRY_INSECURE)" $(PYTHON) "$(DELIVERY_SCRIPT)" --config "$(BUILD_CONFIG)" --cache-images
