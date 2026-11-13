PYTHON ?= python3
NODE ?= node
REPO_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
VERSION = $(shell $(PYTHON) -c 'import tomllib; print(tomllib.load(open("$(REPO_ROOT)/pyproject.toml", "rb"))["project"]["version"])')
BUILD_TIME := $(shell TZ=Asia/Shanghai date +%Y%m%d%H%M)
VCS_REF := $(shell git -C "$(REPO_ROOT)" rev-parse HEAD)
IMAGE_TAG := $(VERSION)-$(BUILD_TIME)-$(shell git -C "$(REPO_ROOT)" rev-parse --short=7 HEAD)
IMAGE ?= mmzhou-os-install-console:$(IMAGE_TAG)
PUBLISH_IMAGE := $(REGISTRY)/pxeye:$(IMAGE_TAG)
BASE_IMAGE ?= ubuntu:24.04
BUILD_CONFIG ?= $(REPO_ROOT)/outputs_/build-config.json
BUILD_WORK_DIRECTORY ?= $(REPO_ROOT)/outputs_
BUNDLE_VERSION ?= bundle-$(VERSION)-$(shell TZ=Asia/Shanghai date +%Y%m%d%H%M)
DELIVERY_SCRIPT := $(REPO_ROOT)/offline-build/delivery.py
VERSION_ARG := $(if $(BUNDLE_VERSION),--version $(BUNDLE_VERSION),)
# The supported field workflow uses an HTTP Registry unless the caller
# explicitly selects TLS.  Export a real default instead of an empty variable.
REGISTRY_INSECURE ?= true
# Optional ARM64 boot-material image.  Keep it disabled unless the input
# directory is intentionally supplied for this build.
INCLUDE_ARM64_MATERIALS ?= 0
ARM64_MATERIALS_DIR ?=
DHCP_TIMEOUT ?= 15
DHCP_ATTEMPTS ?= 3

.PHONY: syntax lint format-check test wheel image images ensure-build-config cache-images bundles dhcp-check dhcp-check-help
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

# Build and publish a version/time/commit-tagged image. The operator updates
# charts/pxeye/values.yaml explicitly before caching images or packaging.
images:
	@test -n "$(REGISTRY)" || { echo "Set REGISTRY=host:port" >&2; exit 1; }
	$(MAKE) --no-print-directory -f "$(REPO_ROOT)/Makefile" image IMAGE="$(PUBLISH_IMAGE)" VCS_REF="$(VCS_REF)" VERSION="$(VERSION)"
	@case "$(REGISTRY_INSECURE)" in 1|true|yes) echo "HTTP Registry: Docker daemon must trust $(REGISTRY) as an insecure registry" ;; esac
	docker push "$(PUBLISH_IMAGE)"
	@echo "PUBLISHED_PXEYE_IMAGE=$(PUBLISH_IMAGE)"
	@echo "Set image in charts/pxeye/values.yaml to $(PUBLISH_IMAGE) before make cache-images / make bundles"

# Build a complete offline delivery from the locked PXEye parent Chart.
# The cache-seed command is idempotent: it exports local containerd images only
# when the Chart-derived closure changes; otherwise it returns immediately.
# Defaults: a build-config.json and outputs_ directory beside this checkout,
# and a PXEye-versioned Asia/Shanghai timestamped bundle version. Override only for a separate workspace
# or a repeatable output version.
ensure-build-config:
	@if test ! -f "$(BUILD_CONFIG)"; then \
		echo "INITIALIZE_BUILD_CONFIG $(BUILD_CONFIG)"; \
		$(PYTHON) "$(DELIVERY_SCRIPT)" --write-config "$(BUILD_CONFIG)" --work-directory "$(BUILD_WORK_DIRECTORY)"; \
	fi
	@test -f "$(BUILD_CONFIG)" || { echo "Missing BUILD_CONFIG=$(BUILD_CONFIG)" >&2; exit 1; }

bundles: ensure-build-config
	@test -n "$(REGISTRY)" || { echo "Set REGISTRY=host:port" >&2; exit 1; }
	REGISTRY="$(REGISTRY)" REGISTRY_INSECURE="$(REGISTRY_INSECURE)" INCLUDE_ARM64_MATERIALS="$(INCLUDE_ARM64_MATERIALS)" ARM64_MATERIALS_DIR="$(ARM64_MATERIALS_DIR)" $(PYTHON) "$(DELIVERY_SCRIPT)" --config "$(BUILD_CONFIG)" $(VERSION_ARG)

cache-images: ensure-build-config
	@test -n "$(REGISTRY)" || { echo "Set REGISTRY=host:port" >&2; exit 1; }
	REGISTRY="$(REGISTRY)" REGISTRY_INSECURE="$(REGISTRY_INSECURE)" INCLUDE_ARM64_MATERIALS="$(INCLUDE_ARM64_MATERIALS)" ARM64_MATERIALS_DIR="$(ARM64_MATERIALS_DIR)" $(PYTHON) "$(DELIVERY_SCRIPT)" --config "$(BUILD_CONFIG)" --cache-images

# Run on the client VLAN; this sends Discover only and never configures an IP.
dhcp-check:
	@if test "$(HELP)" = "1" || test -z "$(IFACE)"; then \
		$(PYTHON) "$(REPO_ROOT)/tools/dhcp-check.py" --help; \
	else \
		$(PYTHON) "$(REPO_ROOT)/tools/dhcp-check.py" --interface "$(IFACE)" --timeout "$(DHCP_TIMEOUT)" --attempts "$(DHCP_ATTEMPTS)" $(if $(DHCP_MAC),--mac "$(DHCP_MAC)",) $(if $(DHCP_SERVER),--server "$(DHCP_SERVER)",) $(if $(DHCP_SUBNET),--subnet "$(DHCP_SUBNET)",) $(if $(DHCP_REPORT),--report "$(DHCP_REPORT)",); \
	fi

dhcp-check-help:
	@$(PYTHON) "$(REPO_ROOT)/tools/dhcp-check.py" --help
