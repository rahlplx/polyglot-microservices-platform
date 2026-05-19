# ===========================================================================
# Gateway Service - Multi-stage OCI build
# ===========================================================================
# Stage 1: Build the Go binary
# Stage 2: Create a minimal runtime image using distroless
# ===========================================================================

# ---------------------------------------------------------------------------
# Stage 1: Builder
# ---------------------------------------------------------------------------
FROM golang:1.22.4-bookworm AS builder

# Build arguments for version injection
ARG VERSION=0.1.0
ARG COMMIT_SHA=unknown
ARG BUILD_DATE=unknown

# Set environment variables for static Go build
ENV CGO_ENABLED=0 \
    GOOS=linux \
    GOARCH=amd64 \
    GO111MODULE=on

WORKDIR /build

# Cache dependency downloads by copying go.mod/go.sum first
COPY go.mod go.sum ./
RUN go mod download

# Copy source code
COPY . .

# Build the binary with version information injected via ldflags
RUN go build \
    -ldflags="-s -w \
      -X main.version=${VERSION} \
      -X main.commitSha=${COMMIT_SHA} \
      -X main.buildDate=${BUILD_DATE}" \
    -trimpath \
    -o /bin/gateway \
    ./cmd/

# Verify the binary is statically linked
RUN file /bin/gateway && \
    /bin/gateway --version 2>/dev/null || true

# ---------------------------------------------------------------------------
# Stage 2: Runtime (distroless for minimal attack surface)
# ---------------------------------------------------------------------------
FROM gcr.io/distroless/static-debian12:nonroot AS runtime

# Copy the binary from the builder stage
COPY --from=builder /bin/gateway /bin/gateway

# Copy the API proto and OpenAPI specs for discovery
COPY --from=builder /build/api/ /opt/gateway/api/

# Use non-root user (65532 = nonroot in distroless)
USER 65532:65532

# Expose ports (HTTP: 8080, gRPC: 9090)
EXPOSE 8080 9090

# Health check via the unauthenticated health endpoint
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
    CMD ["/bin/gateway", "healthcheck"]

# Entry point
ENTRYPOINT ["/bin/gateway"]
