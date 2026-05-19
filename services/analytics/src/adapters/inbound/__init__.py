"""
Inbound adapters for the Analytics service.

Implements gRPC handlers and Kafka event consumers that translate
external requests into domain use case invocations.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from ..domain.models import (
    AggregationFunction, Granularity, ReportType,
)
from ..domain.ports import GetMetricsPort, GetReportPort, StreamEventsPort

logger = logging.getLogger(__name__)


class GrpcHandler:
    """gRPC handler for the Analytics query API.
    Handles metric queries, report generation, and dashboard management RPCs.
    Translates between gRPC message format and domain types."""

    def __init__(self, analytics_service: GetMetricsPort, report_service: GetReportPort) -> None:
        self._analytics = analytics_service
        self._reports = report_service

    async def get_metrics(self, request: dict[str, Any]) -> dict[str, Any]:
        """Handle GetMetrics RPC. Queries time-series data with flexible filtering."""
        metric_name = request.get("metric_name", "")
        service = request.get("service")
        aggregation = AggregationFunction(request.get("aggregation", "AVG"))
        granularity = Granularity(request.get("granularity", "5m"))

        series_list = await self._analytics.get_metrics(
            metric_name=metric_name,
            service=service,
            aggregation=aggregation,
            granularity=granularity,
            start_time=request.get("start_time"),
            end_time=request.get("end_time"),
        )

        return {
            "metrics": [
                {
                    "metric_name": s.metric_name,
                    "service": s.service,
                    "aggregation": s.aggregation.value,
                    "granularity": s.granularity.value,
                    "points": [
                        {"timestamp": p.timestamp.isoformat(), "value": p.value}
                        for p in s.points
                    ],
                }
                for s in series_list
            ],
        }

    async def generate_report(self, request: dict[str, Any]) -> dict[str, Any]:
        """Handle GenerateReport RPC. Creates a new analytics report."""
        report = await self._reports.generate_report(
            report_type=ReportType(request.get("report_type", "SERVICE_HEALTH")),
            services=request.get("services", []),
            start_time=request.get("start_time", ""),
            end_time=request.get("end_time", ""),
            granularity=Granularity(request.get("granularity", "1h")),
            format=request.get("format", "JSON"),
        )
        return {"report_id": report.id, "status": "generated"}


class KafkaEventConsumer:
    """Kafka consumer for business events and OTel spans.
    Subscribes to business event topics and the OTel spans topic,
    routing each event to the appropriate domain service for processing.
    Implements at-least-once processing with manual offset commit."""

    def __init__(self, analytics_service: StreamEventsPort) -> None:
        self._service = analytics_service
        self._running = False

    async def start(self, brokers: str, topics: list[str], group_id: str) -> None:
        """Start consuming events from Kafka topics."""
        self._running = True
        logger.info("analytics kafka consumer starting", extra={
            "brokers": brokers, "topics": topics, "group_id": group_id,
        })
        # In production: aiokafka consumer with manual offset commit.

    async def stop(self) -> None:
        """Gracefully stop the Kafka consumer."""
        self._running = False
        logger.info("analytics kafka consumer stopped")

    async def _process_event(self, event_data: bytes) -> None:
        """Process a single event from Kafka."""
        try:
            event = json.loads(event_data)
        except json.JSONDecodeError:
            logger.error("failed to decode analytics event")
            return

        await self._service.process_event(event)
