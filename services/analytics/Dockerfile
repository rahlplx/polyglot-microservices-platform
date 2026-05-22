# Build stage
FROM python:3.12-slim AS builder

WORKDIR /app

COPY pyproject.toml ./
RUN pip install --no-cache-dir hatchling && pip install --no-cache-dir .

COPY src/ src/
RUN pip install --no-cache-dir .

# Runtime stage
FROM python:3.12-slim AS runtime

RUN groupadd -r analytics && useradd -r -g analytics analytics

COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY src/ /app/src/

WORKDIR /app

USER analytics

EXPOSE 50057 8087 9097

CMD ["python", "-m", "analytics_service.src.main"]
