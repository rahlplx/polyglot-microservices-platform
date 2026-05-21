"""
Processing outbound adapters for the Analytics service.

This package contains the OTel span processor adapter that extracts service
metrics from distributed traces and writes them to the time series store.
The processor handles both ingested telemetry from other services and
self-monitoring telemetry, carefully separating the two to prevent
feedback loops.
"""
