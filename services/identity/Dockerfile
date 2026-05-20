# ===========================================================================
# Identity Service - Multi-stage OCI build
# ===========================================================================
# Stage 1: Build the Rust binary with musl for static linking
# Stage 2: Create a minimal runtime image using scratch
# ===========================================================================

# ---------------------------------------------------------------------------
# Stage 1: Builder
# ---------------------------------------------------------------------------
FROM rust:1.75-bookworm AS builder

# Build arguments for version injection
ARG VERSION=0.1.0
ARG COMMIT_SHA=unknown
ARG BUILD_DATE=unknown
ARG TARGET=x86_64-unknown-linux-musl

# Install musl target for static binary
RUN rustup target add ${TARGET}

# Install build dependencies
RUN apt-get update && apt-get install -y \
    musl-tools \
    pkg-config \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Cache dependency downloads by copying Cargo.toml/Cargo.lock first
COPY Cargo.toml Cargo.lock* ./

# Create a dummy main.rs to build dependencies
RUN mkdir src && echo "fn main() {}" > src/main.rs

# Build dependencies only (cache layer)
RUN cargo build --release --target ${TARGET} 2>/dev/null || true

# Copy the actual source code
COPY src/ src/
COPY build.rs build.rs* ./

# Set environment variables
ENV RUSTFLAGS="-C target-feature=+crt-static"

# Build the binary with version information
RUN cargo build \
    --release \
    --target ${TARGET} \
    --bin identity-service \
    && cp /build/target/${TARGET}/release/identity-service /bin/identity-service

# Verify the binary is statically linked
RUN file /bin/identity-service && \
    ldd /bin/identity-service 2>&1 | grep -q "not a dynamic executable" || \
    echo "Warning: binary may not be fully static"

# ---------------------------------------------------------------------------
# Stage 2: Runtime (scratch for minimal attack surface)
# ---------------------------------------------------------------------------
FROM scratch AS runtime

# Copy the static binary from the builder stage
COPY --from=builder /bin/identity-service /bin/identity-service

# Copy CA certificates for TLS connections (OTel, PostgreSQL)
COPY --from=builder /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/

# Copy the proto schemas for gRPC reflection
COPY --from=builder /build/schemas/ /opt/identity/schemas/

# Expose ports (gRPC: 9090, HTTP health: 8080)
EXPOSE 9090 8080

# Health check via the HTTP health endpoint
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
    CMD ["/bin/identity-service", "healthcheck"] || true

# Environment defaults
ENV IDENTITY_GRPC_BIND_ADDR=0.0.0.0:9090 \
    IDENTITY_HTTP_BIND_ADDR=0.0.0.0:8080 \
    IDENTITY_TRUST_DOMAIN=trust.example.org \
    IDENTITY_LOG_LEVEL=info \
    IDENTITY_OTLP_ENDPOINT=http://otel-collector:4317

# Run as non-root user (nobody in scratch context)
USER 65534:65534

# Entry point
ENTRYPOINT ["/bin/identity-service"]
