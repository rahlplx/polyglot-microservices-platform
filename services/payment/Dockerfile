# Build stage
FROM golang:1.25-alpine AS builder

RUN apk add --no-cache git ca-certificates

WORKDIR /app

COPY go.mod go.sum ./
RUN go mod download

COPY . .

RUN CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build \
    -ldflags="-w -s" \
    -o /bin/payment-service \
    ./cmd/main.go

# Runtime stage
FROM gcr.io/distroless/static-debian12:nonroot

COPY --from=builder /bin/payment-service /payment-service
COPY --from=builder /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/

USER nonroot:nonroot

EXPOSE 50054 9094

ENTRYPOINT ["/payment-service"]
