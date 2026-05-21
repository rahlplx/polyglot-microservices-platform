# =============================================================================
# Multi-stage Dockerfile for Catalog Service
# Stage 1: Build - Compile TypeScript and install production dependencies
# Stage 2: Runtime - Minimal image with compiled JS and production node_modules
# =============================================================================

# ---------------------------------------------------------------------------
# Stage 1: Build
# ---------------------------------------------------------------------------
FROM node:20-bookworm AS builder

WORKDIR /app

# Copy package manifests first for layer caching
COPY package.json package-lock.json* ./

# Install ALL dependencies (including devDependencies for build)
RUN npm ci --ignore-scripts

# Copy source code and configuration
COPY tsconfig.json ./
COPY src/ ./src/

# Compile TypeScript to JavaScript
RUN npm run build

# Prune devDependencies after build
RUN npm prune --production

# ---------------------------------------------------------------------------
# Stage 2: Runtime
# ---------------------------------------------------------------------------
FROM node:20-slim AS runtime

# Install dumb-init for proper signal handling
RUN apt-get update && \
    apt-get install -y --no-install-recommends dumb-init && \
    rm -rf /var/lib/apt/lists/*

# Create non-root user for security
RUN groupadd --gid 1001 catalog && \
    useradd --uid 1001 --gid catalog --shell /bin/bash --create-home catalog

WORKDIR /app

# Copy built application from builder stage
COPY --from=builder /app/dist ./dist
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/package.json ./

# Set environment variables
ENV NODE_ENV=production
ENV NODE_OPTIONS="--max-old-space-size=256"

# Expose service ports
# 50053 = gRPC (as defined in PHASE2_DESIGN_SPEC)
# 3000  = HTTP/REST (Fastify)
EXPOSE 50053 3000

# Switch to non-root user
USER catalog

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD node -e "const http = require('http'); const req = http.request({hostname:'localhost',port:3000,path:'/healthz',method:'GET',timeout:2000}, res => {process.exit(res.statusCode === 200 ? 0 : 1)}); req.on('error', () => process.exit(1)); req.end()"

# Use dumb-init to handle signals properly
ENTRYPOINT ["dumb-init", "--"]

# Start the service
CMD ["node", "dist/main.js"]
