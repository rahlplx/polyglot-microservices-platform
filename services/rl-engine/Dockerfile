# Build stage
FROM python:3.12-slim AS builder

WORKDIR /app

COPY pyproject.toml ./
RUN pip install --no-cache-dir hatchling && pip install --no-cache-dir .

COPY src/ src/
RUN pip install --no-cache-dir .

# Runtime stage
FROM python:3.12-slim AS runtime

RUN groupadd -r rlengine && useradd -r -g rlengine rlengine

COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY src/ /app/src/

WORKDIR /app

USER rlengine

EXPOSE 50058 8088 9098

CMD ["python", "-m", "rl_engine_service.src.main"]
