# =============================================================================
# Catalog Service Makefile
# =============================================================================

.PHONY: build clean dev lint test test-unit test-contract test-integration \
        test-coverage proto docker-build docker-run typecheck help

# Default target
.DEFAULT_GOAL := help

# ---------------------------------------------------------------------------
# Variables
# ---------------------------------------------------------------------------
SERVICE_NAME    := catalog
DOCKER_REGISTRY := ghcr.io/comprehensive-architecture
DOCKER_IMAGE    := $(DOCKER_REGISTRY)/$(SERVICE_NAME)
VERSION         := $(shell git describe --tags --always --dirty 2>/dev/null || echo "0.1.0-dev")
NODE_MODULES    := node_modules
DIST            := dist

# ---------------------------------------------------------------------------
# Development
# ---------------------------------------------------------------------------

## dev: Start the service in development mode with hot-reload
dev:
	npm run dev

## install: Install dependencies
install:
	npm ci

## install:dev: Install dependencies including devDependencies
install:dev:
	npm install

# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

## build: Compile TypeScript to JavaScript
build: clean-dist
	npm run build

## clean: Remove build artifacts and node_modules
clean:
	rm -rf $(DIST) $(NODE_MODULES) coverage

## clean-dist: Remove only compiled output
clean-dist:
	rm -rf $(DIST)

## typecheck: Run TypeScript type checking without emitting
typecheck:
	npm run typecheck

# ---------------------------------------------------------------------------
# Code Quality
# ---------------------------------------------------------------------------

## lint: Run ESLint on source files
lint:
	npm run lint

## lint:fix: Run ESLint and auto-fix issues
lint:fix:
	npm run lint:fix

# ---------------------------------------------------------------------------
# Testing
# ---------------------------------------------------------------------------

## test: Run all test suites
test:
	npm test

## test:unit: Run unit tests only
test:unit:
	npm run test:unit

## test:contract: Run contract tests only
test:contract:
	npm run test:contract

## test:integration: Run integration tests only
test:integration:
	npm run test:integration

## test:coverage: Run tests with coverage report
test:coverage:
	npm run test:coverage

# ---------------------------------------------------------------------------
# Code Generation
# ---------------------------------------------------------------------------

## proto: Generate TypeScript/JavaScript stubs from protobuf definitions
proto:
	npm run proto:generate

# ---------------------------------------------------------------------------
# Docker
# ---------------------------------------------------------------------------

## docker:build: Build Docker image
docker:build:
	docker build -t $(DOCKER_IMAGE):$(VERSION) \
	             -t $(DOCKER_IMAGE):latest \
	             --label version=$(VERSION) \
	             --label service=$(SERVICE_NAME) .

## docker:run: Run Docker container locally
docker:run:
	docker run --rm -p 3000:3000 -p 50053:50053 \
	          --env-file .env \
	          $(DOCKER_IMAGE):$(VERSION)

## docker:push: Push Docker image to registry
docker:push:
	docker push $(DOCKER_IMAGE):$(VERSION)
	docker push $(DOCKER_IMAGE):latest

# ---------------------------------------------------------------------------
# Help
# ---------------------------------------------------------------------------

## help: Show this help message
help:
	@echo "Catalog Service - Available Commands"
	@echo "====================================="
	@grep -E '^## ' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ": "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}' | \
		sed 's/^## //'
