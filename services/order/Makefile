.PHONY: build test lint docker docker-push clean generate-proto generate-jooq run

# Configuration
SERVICE_NAME    := order-service
IMAGE_NAME      := company/$(SERVICE_NAME)
IMAGE_TAG       := latest
GRPC_PORT       := 50054
HTTP_PORT       := 8084
GRADLE          := ./gradlew

# --- Build ---

build:
	$(GRADLE) build -x test

test:
	$(GRADLE) test

lint:
	$(GRADLE) ktlintCheck || true

# --- Code Generation ---

generate-proto:
	$(GRADLE) generateProto

generate-jooq:
	@echo "Run 'make db-push' first to create schema, then:"
	$(GRADLE) generateJooq

# --- Database ---

db-push:
	@echo "Push database schema (requires Prisma or Flyway setup)"
	@echo "For development, use: docker-compose up -d postgres"
	@echo "Then: $(GRADLE) flywayMigrate"

db-reset:
	@echo "Reset database (destructive!)"
	docker-compose down -v postgres

# --- Docker ---

docker:
	docker build -t $(IMAGE_NAME):$(IMAGE_TAG) .

docker-push: docker
	docker push $(IMAGE_NAME):$(IMAGE_TAG)

docker-run: docker
	docker run -d \
		--name $(SERVICE_NAME) \
		-p $(GRPC_PORT):$(GRPC_PORT) \
		-p $(HTTP_PORT):$(HTTP_PORT) \
		-e DATABASE_URL=jdbc:postgresql://host.docker.internal:5432/orderdb \
		-e DATABASE_USERNAME=order \
		-e DATABASE_PASSWORD=order \
		-e KAFKA_BOOTSTRAP_SERVERS=host.docker.internal:9092 \
		-e OTEL_EXPORTER_OTLP_ENDPOINT=http://host.docker.internal:4317 \
		$(IMAGE_NAME):$(IMAGE_TAG)

# --- Run ---

run:
	$(GRADLE) run

# --- Clean ---

clean:
	$(GRADLE) clean

# --- Development ---

dev: ## Start development environment with hot reload
	$(GRADLE) -t run

format:
	$(GRADLE) ktlintFormat || true

# --- Dependencies ---

deps:
	$(GRADLE) dependencies

outdated:
	$(GRADLE) dependencyUpdates || true

# --- Help ---

help:
	@echo "Order Service - Makefile Commands"
	@echo ""
	@echo "  build            Build the application (skip tests)"
	@echo "  test             Run all tests (unit, contract, property)"
	@echo "  lint             Run ktlint code style checks"
	@echo "  generate-proto   Generate gRPC/Kotlin code from proto schemas"
	@echo "  generate-jooq    Generate jOOQ code from database schema"
	@echo "  db-push          Push database schema migrations"
	@echo "  docker           Build Docker image"
	@echo "  docker-push      Push Docker image to registry"
	@echo "  docker-run       Run Docker container locally"
	@echo "  run              Run the application"
	@echo "  dev              Run with hot reload"
	@echo "  clean            Clean build artifacts"
	@echo "  format           Auto-format code with ktlint"
	@echo "  deps             Show dependency tree"
	@echo "  outdated         Check for dependency updates"
