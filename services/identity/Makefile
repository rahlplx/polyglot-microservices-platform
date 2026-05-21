# ===========================================================================
# Identity Service - Makefile
# ===========================================================================
# Targets: build, test, lint, generate, docker-build
# ===========================================================================

# Configuration
BINARY       := identity-service
VERSION      := $(shell git describe --tags --always --dirty 2>/dev/null || echo "0.1.0")
COMMIT_SHA   := $(shell git rev-parse --short HEAD 2>/dev/null || echo "unknown")
BUILD_DATE   := $(shell date -u +%Y-%m-%dT%H:%M:%SZ)
TARGET       := x86_64-unknown-linux-musl

DOCKER_REGISTRY := ghcr.io/comprehensive-architecture
DOCKER_IMAGE := $(DOCKER_REGISTRY)/identity-service
DOCKER_TAG   := $(VERSION)

# Rust tools
CARGO    := cargo
CLIPPY   := cargo clippy
RUSTFMT  := rustfmt
BUF      := buf

# ---------------------------------------------------------------------------
# Primary targets
# ---------------------------------------------------------------------------

.PHONY: all
all: generate lint test build ## Run generate, lint, test, and build

# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

.PHONY: build
build: ## Build the identity-service binary (release, musl static)
	cargo build --release --target $(TARGET)
	@echo "Built target/$(TARGET)/release/$(BINARY) (version=$(VERSION), commit=$(COMMIT_SHA))"

.PHONY: build-debug
build-debug: ## Build with debug symbols
	cargo build
	@echo "Built debug binary"

.PHONY: build-linux
build-linux: ## Build for Linux (musl static) using cross
	cross build --release --target $(TARGET)
	@echo "Built for $(TARGET)"

# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------

.PHONY: test
test: ## Run all tests
	cargo test --all-features -- --test-threads=4

.PHONY: test-unit
test-unit: ## Run unit tests only
	cargo test --lib -- --test-threads=4

.PHONY: test-contract
test-contract: ## Run contract tests only
	cargo test --test identity_contract_test -- --test-threads=1

.PHONY: test-property
test-property: ## Run property-based tests only
	cargo test --test svid_property_test -- --test-threads=1

.PHONY: test-coverage
test-coverage: ## Run tests with coverage report (requires cargo-tarpaulin)
	cargo tarpaulin --out Html --output-dir coverage/
	@echo "Coverage report: coverage/index.html"

# ---------------------------------------------------------------------------
# Lint
# ---------------------------------------------------------------------------

.PHONY: lint
lint: ## Run clippy with strict lints
	RUSTFLAGS="-D warnings" cargo clippy --all-targets --all-features -- \
		-W clippy::all \
		-W clippy::pedantic \
		-W clippy::cargo \
		-A clippy::module-name-repetitions \
		-A clippy::too-many-arguments \
		-A clippy::type-complexity

.PHONY: lint-fix
lint-fix: ## Run clippy with auto-fix
	cargo clippy --fix --allow-dirty

.PHONY: fmt
fmt: ## Format Rust code
	cargo fmt --all -- --check

.PHONY: fmt-fix
fmt-fix: ## Format Rust code (write changes)
	cargo fmt --all

.PHONY: vet
vet: ## Run cargo check
	cargo check --all-features

# ---------------------------------------------------------------------------
# Generate
# ---------------------------------------------------------------------------

.PHONY: generate
generate: ## Generate code from protobuf definitions
	cargo build # Trigger build.rs which runs tonic-build
	@echo "Code generation complete"

.PHONY: proto
proto: ## Generate Rust code from protobuf definitions using buf
	$(BUF) generate --template buf.gen.yaml
	@echo "Proto code generation complete"

# ---------------------------------------------------------------------------
# Docker
# ---------------------------------------------------------------------------

.PHONY: docker-build
docker-build: ## Build the Docker image (multi-stage, musl static binary)
	docker build \
		--build-arg VERSION=$(VERSION) \
		--build-arg COMMIT_SHA=$(COMMIT_SHA) \
		--build-arg BUILD_DATE=$(BUILD_DATE) \
		-t $(DOCKER_IMAGE):$(DOCKER_TAG) \
		-t $(DOCKER_IMAGE):latest \
		.
	@echo "Built $(DOCKER_IMAGE):$(DOCKER_TAG)"

.PHONY: docker-push
docker-push: docker-build ## Push the Docker image to the registry
	docker push $(DOCKER_IMAGE):$(DOCKER_TAG)
	docker push $(DOCKER_IMAGE):latest
	@echo "Pushed $(DOCKER_IMAGE):$(DOCKER_TAG) and :latest"

.PHONY: docker-run
docker-run: docker-build ## Run the Docker image locally
	docker run --rm \
		-p 9090:9090 \
		-p 8080:8080 \
		-e IDENTITY_TRUST_DOMAIN=trust.dev.example.org \
		-e IDENTITY_LOG_LEVEL=debug \
		-e IDENTITY_OTLP_ENDPOINT=host.docker.internal:4317 \
		$(DOCKER_IMAGE):$(DOCKER_TAG)

# ---------------------------------------------------------------------------
# Development
# ---------------------------------------------------------------------------

.PHONY: run
run: ## Run the identity service locally
	cargo run

.PHONY: check
check: ## Quick check (faster than build)
	cargo check

.PHONY: clean
clean: ## Remove build artifacts
	cargo clean
	rm -rf coverage/
	@echo "Cleaned build artifacts"

.PHONY: deps
deps: ## Show dependency tree
	cargo tree

.PHONY: outdated
outdated: ## Check for outdated dependencies (requires cargo-outdated)
	cargo outdated

.PHONY: audit
audit: ## Check for security vulnerabilities (requires cargo-audit)
	cargo audit

# ---------------------------------------------------------------------------
# Help
# ---------------------------------------------------------------------------

.PHONY: help
help: ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'
