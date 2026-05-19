.PHONY: build test lint generate docker clean

# Build the payment service binary
build:
	go build -o bin/payment-service ./cmd/main.go

# Run all tests with coverage
test:
	go test -v -race -coverprofile=coverage.out ./...
	go tool cover -func=coverage.out | tail -1

# Run linter
lint:
	golangci-lint run ./...

# Generate proto stubs
generate:
	protoc --go_out=. --go-grpc_out=. api/proto/payment.proto

# Build Docker image
docker:
	docker build -t gstack/payment-service:latest .

# Clean build artifacts
clean:
	rm -rf bin/ coverage.out

# Run with default config
run:
	go run ./cmd/main.go
