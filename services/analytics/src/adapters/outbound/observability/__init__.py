"""
Observability outbound adapters for the Analytics service.

This package contains the self-instrumentation adapter that configures
OpenTelemetry SDK for the Analytics service's own operations. The service
is unique in that it both produces and consumes OTel telemetry, so
self-monitoring metrics are carefully separated from ingested metrics
to prevent feedback loops.
"""
