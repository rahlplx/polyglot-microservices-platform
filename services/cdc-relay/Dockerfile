FROM python:3.12-slim AS builder

WORKDIR /app
COPY pyproject.toml ./
RUN pip install --no-cache-dir hatchling && pip install --no-cache-dir .
COPY src/ src/

FROM python:3.12-slim AS runtime

RUN groupadd -r cdc-relay && useradd -r -g cdc-relay cdc-relay

COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /app/src /app/src

WORKDIR /app
USER cdc-relay

EXPOSE 50060 9090

CMD ["python", "-m", "src.main"]
