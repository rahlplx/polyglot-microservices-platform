# Build stage
FROM gradle:8-jdk21 AS builder

WORKDIR /app

# Copy build files first for dependency caching
COPY build.gradle.kts settings.gradle.kts ./

# Download dependencies (cached layer)
RUN gradle dependencies --no-daemon || true

# Copy source code
COPY src ./src

# Build the application
RUN gradle build --no-daemon -x test \
    && cp build/libs/*-SNAPSHOT.jar app.jar || \
    cp build/libs/*.jar app.jar 2>/dev/null || \
    find build/libs -name "*.jar" -exec cp {} app.jar \;

# Runtime stage
FROM eclipse-temurin:21-jre-alpine

LABEL maintainer="architecture-team@company.com"
LABEL service="order-service"
LABEL version="1.0.0"
LABEL description="Order service with saga orchestration and transactional outbox pattern"

# Install minimal runtime dependencies
RUN apk add --no-cache curl && \
    addgroup -S appgroup && \
    adduser -S appuser -G appgroup

WORKDIR /app

# Copy the built JAR
COPY --from=builder /app/app.jar app.jar

# Create directory for SPIRE Agent socket
RUN mkdir -p /tmp/spire-agent/public && \
    chown -R appuser:appgroup /app /tmp/spire-agent

# Switch to non-root user
USER appuser

# Expose gRPC and HTTP ports
EXPOSE 50054 8084

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8084/health || exit 1

# JVM options for containerized environment
ENV JAVA_OPTS="-XX:MaxRAMPercentage=75.0 \
    -XX:+UseG1GC \
    -XX:+UseContainerSupport \
    -XX:MaxGCPauseMillis=200 \
    -Djava.security.egd=file:/dev/./urandom"

# Application configuration via environment
ENV APP_ENV=production
ENV GRPC_PORT=50054
ENV HTTP_PORT=8084

ENTRYPOINT ["sh", "-c", "java $JAVA_OPTS -jar app.jar"]
