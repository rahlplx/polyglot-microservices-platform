# Build stage
FROM python:3.12-slim AS builder

WORKDIR /app

COPY pyproject.toml ./
RUN pip install --no-cache-dir hatchling && pip install --no-cache-dir .

COPY src/ src/
RUN pip install --no-cache-dir .

# Runtime stage
FROM python:3.12-slim AS runtime

RUN groupadd -r notification && useradd -r -g notification notification

COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY src/ /app/src/

WORKDIR /app

USER notification

EXPOSE 50056 8086 9096

CMD ["python", "-m", "notification_service.src.main"]
