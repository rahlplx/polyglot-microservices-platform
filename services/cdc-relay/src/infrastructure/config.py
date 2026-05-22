"""CDC Relay — Configuration"""
from __future__ import annotations
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    kafka_connect_url: str
    grpc_port: int = 50060
    metrics_port: int = 9090
    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            kafka_connect_url=os.environ.get("KAFKA_CONNECT_URL", "http://kafka-connect:8083"),
            grpc_port=int(os.environ.get("GRPC_PORT", "50060")),
            metrics_port=int(os.environ.get("METRICS_PORT", "9090")),
            log_level=os.environ.get("LOG_LEVEL", "INFO"),
        )
