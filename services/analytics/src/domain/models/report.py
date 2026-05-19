"""
Report domain model for the Analytics service.

This module defines the Report entity and its associated enumerations for
report types, granularity levels, and output formats. Reports are pre-configured
analytical templates that encapsulate complex multi-metric queries into a
single, well-structured output suitable for business stakeholders. Each report
type targets a specific business domain: revenue summaries, order funnel
analysis, inventory velocity tracking, and more.

The TimeRange value object encapsulates the temporal scope of a report, ensuring
that all report queries use consistent time boundaries. Granularity controls
the resolution of data points within the report, from hourly detail to monthly
summaries. The separation of report metadata (type, parameters, format) from
the actual data payload allows the system to cache and reuse report definitions
independently of the data they contain.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class ReportType(Enum):
    """Predefined analytical report templates.

    Each report type encapsulates a specific business analysis pattern with
    predefined metrics, dimensions, and visualization recommendations.
    The enum values map to transformer functions that convert raw time
    series data into curated business insights.
    """

    REVENUE_SUMMARY = "revenue_summary"
    ORDER_FUNNEL = "order_funnel"
    INVENTORY_VELOCITY = "inventory_velocity"
    PAYMENT_HEALTH = "payment_health"
    NOTIFICATION_EFFECTIVENESS = "notification_effectiveness"
    SERVICE_SLA = "service_sla"
    CUSTOMER_LIFETIME_VALUE = "customer_lifetime_value"


class Granularity(Enum):
    """Temporal resolution for report data points.

    Granularity determines the interval between data points in a report.
    Finer granularity provides more detail but increases query cost and
    result size. Coarser granularity enables faster queries and compact
    results suitable for long-term trend analysis. The aggregation engine
    uses these values to select the appropriate pre-computed rollup table.
    """

    HOURLY = "hourly"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class ReportFormat(Enum):
    """Output format for report generation.

    JSON format is suitable for programmatic consumption by dashboards
    and APIs. CSV format enables spreadsheet analysis and data exchange
    with external tools. PDF format produces formatted documents suitable
    for executive presentations and archival.
    """

    JSON = "json"
    CSV = "csv"
    PDF = "pdf"


@dataclass(frozen=True)
class TimeRange:
    """A closed time interval with inclusive start and end timestamps.

    TimeRange is a value object used throughout the analytics domain to
    specify the temporal scope of queries, reports, and dashboard panels.
    The frozen dataclass ensures immutability, preventing accidental
    modification of time ranges that are shared across multiple queries
    or cached results. Validation is performed at construction time to
    prevent invalid ranges where the start timestamp exceeds the end.
    """

    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        """Validate that the time range is well-formed.

        Raises a ValueError if the start timestamp is after the end
        timestamp, which would produce nonsensical query results. This
        validation runs automatically during construction to catch
        configuration errors early.
        """
        if self.start > self.end:
            raise ValueError(
                f"TimeRange start ({self.start}) must not exceed end ({self.end})"
            )

    @property
    def duration_seconds(self) -> float:
        """Return the duration of the time range in seconds.

        This property supports the aggregation engine's decision-making
        about which rollup table to query: longer durations favor coarser
        rollups for performance, while shorter durations can use raw data
        for maximum detail.
        """
        return (self.end - self.start).total_seconds()

    @property
    def duration_hours(self) -> float:
        """Return the duration of the time range in hours.

        Convenience property for report generation logic that operates
        in hourly granularity, such as calculating hourly averages from
        daily totals.
        """
        return self.duration_seconds / 3600.0

    def to_dict(self) -> dict[str, Any]:
        """Convert the time range to a plain dictionary representation.

        Serializes timestamps as ISO 8601 strings for JSON compatibility.
        """
        return {
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
        }


@dataclass
class Report:
    """A generated analytical report with metadata and data payload.

    Reports are the primary output artifact of the analytics service for
    business stakeholders. Each report has a type that determines its
    structure and the metrics it includes, a time range that scopes the
    data, and a format that controls the output representation. The
    data field contains the actual report content, which may be structured
    JSON, CSV text, or binary PDF data depending on the format.

    Reports are cached for 5 minutes after generation to support repeated
    downloads without regenerating the underlying data. The report_id
    provides a stable reference for cache lookups and audit trails.
    """

    report_id: str
    report_type: ReportType
    time_range: TimeRange
    format: ReportFormat
    generated_at: datetime
    data: Any = None
    parameters: dict[str, str] = field(default_factory=dict)
    granularity: Granularity = Granularity.DAILY

    def to_dict(self) -> dict[str, Any]:
        """Convert the report to a plain dictionary representation.

        Includes all metadata and the data payload. The data payload is
        included as-is, since its structure depends on the report format.
        For CSV and PDF formats, the data field contains the raw content
        as a string or bytes respectively.
        """
        return {
            "report_id": self.report_id,
            "report_type": self.report_type.value,
            "time_range": self.time_range.to_dict(),
            "format": self.format.value,
            "generated_at": self.generated_at.isoformat(),
            "parameters": dict(self.parameters),
            "granularity": self.granularity.value,
        }
