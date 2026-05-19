# ===========================================================================
# Schema Registry Service - Makefile
# ===========================================================================
# Targets: build, test, lint, generate, docker-build, docker-push
# ===========================================================================

# Configuration
MODULE       := github.com/gstack/schema-registry-service
BINARY       := schema-registry
CMD          := ./cmd/
VERSION      := $(shell git describe --tags --always --dirty 2>/dev/null || echo "1.0.0")
COMMIT_SHA   := $(shell git rev-parse --short HEAD 2>/dev/null || echo "unknown")
BUILD_DATE   := $(shell date -u +%Y-%m-%dT%H:%M:%SZ)
DOCKER_REGISTRY := ghcr.io/gstack
DOCKER_IMAGE := $(DOCKER_REGISTRY)/schema-registry
DOCKER_TAG   := $(VERSION)

# Go tools
GOLINT      := golangci-lint
BUF         := buf

# Build flags
LDFLAGS := -s -w \
  -X main.version=$(VERSION) \
  -X main.commitSha=$(COMMIT_SHA) \
  -X main.buildDate=$(BUILD_DATE)

# ---------------------------------------------------------------------------
# Primary targets
# ---------------------------------------------------------------------------

.PHONY: all
all: generate lint test build ## Run generate, lint, test, and build

# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

.PHONY: build
build: ## Build the schema-registry binary
	CGO_ENABLED=0 go build \
		-ldflags="$(LDFLAGS)" \
		-trimpath \
		-o bin/$(BINARY) \
		$(CMD)
	@echo "Built bin/$(BINARY) (version=$(VERSION), commit=$(COMMIT_SHA))"

.PHONY: build-debug
build-debug: ## Build with debug symbols and race detector
	CGO_ENABLED=1 go build \
		-race \
		-ldflags="-X main.version=$(VERSION)-debug" \
		-o bin/$(BINARY)-debug \
		$(CMD)
	@echo "Built bin/$(BINARY)-debug (debug build with race detector)"

# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------

.PHONY: test
test: ## Run all tests
	go test -v -race -count=1 -timeout=60s ./...

.PHONY: test-unit
test-unit: ## Run unit tests only
	go test -v -race -count=1 -timeout=30s ./domain/... ./tests/unit/...

.PHONY: test-contract
test-contract: ## Run contract tests only
	go test -v -race -count=1 -timeout=30s ./tests/contract/...

.PHONY: test-integration
test-integration: ## Run integration tests only
	go test -v -race -count=1 -timeout=60s ./tests/integration/...

.PHONY: test-coverage
test-coverage: ## Run tests with coverage report
	go test -v -race -coverprofile=coverage.out -covermode=atomic ./...
	go tool cover -html=coverage.out -o coverage.html
	@echo "Coverage report: coverage.html"

# ---------------------------------------------------------------------------
# Lint
# ---------------------------------------------------------------------------

.PHONY: lint
lint: ## Run golangci-lint
	$(GOLINT) run --timeout=5m ./...

.PHONY: lint-fix
lint-fix: ## Run golangci-lint with auto-fix
	$(GOLINT) run --fix --timeout=5m ./...

.PHONY: vet
vet: ## Run go vet
	go vet ./...

.PHONY: fmt
fmt: ## Format Go code
	gofmt -s -w .
	goimports -w .

# ---------------------------------------------------------------------------
# Generate
# ---------------------------------------------------------------------------

.PHONY: generate
generate: ## Run go generate and proto code generation
	go generate ./...
	@echo "Code generation complete"

.PHONY: proto
proto: ## Generate Go code from protobuf definitions
	$(BUF) generate
	@echo "Proto code generation complete"

# ---------------------------------------------------------------------------
# Docker
# ---------------------------------------------------------------------------

.PHONY: docker-build
docker-build: ## Build the Docker image
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
		-p 8081:8081 \
		-p 50058:50058 \
		-p 9090:9090 \
		-e SCHEMA_REGISTRY_PG_HOST=host.docker.internal \
		-e SCHEMA_REGISTRY_OTEL_ENDPOINT=host.docker.internal:4317 \
		$(DOCKER_IMAGE):$(DOCKER_TAG)

# ---------------------------------------------------------------------------
# Development
# ---------------------------------------------------------------------------

.PHONY: run
run: ## Run the schema-registry service locally
	go run $(CMD)

.PHONY: tidy
tidy: ## Tidy Go module dependencies
	go mod tidy
	go mod verify

.PHONY: clean
clean: ## Remove build artifacts
	rm -rf bin/ coverage.out coverage.html

# ---------------------------------------------------------------------------
# Help
# ---------------------------------------------------------------------------

.PHONY: help
help: ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'
