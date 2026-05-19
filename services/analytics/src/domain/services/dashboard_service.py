"""
Dashboard configuration and data serving service for the Analytics service.

This module implements the dashboard service that manages dashboard configurations
and serves live data for dashboard panels. Dashboards are stored as JSON
configuration objects in PostgreSQL, each specifying a set of panels with
metric queries, visualization types, and display options. The service
executes all panel queries in parallel for optimal performance and caches
rendered dashboard data for 30 seconds to reduce database load during
frequent refresh cycles.

The service supports dynamic variable substitution, allowing dashboard
consumers to customize queries at runtime (e.g., selecting a specific
service, environment, or customer segment). Variables are substituted
into panel queries before execution, enabling parameterized dashboards
that adapt to the viewer's context.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import Any

from ..models.aggregation import AggregationFunction, AggregationWindow
from ..models.report import TimeRange
from ..ports.outbound.event_store import EventRepository
from ..ports.outbound.time_series_store import TimeSeriesRepository

logger = logging.getLogger(__name__)


class DashboardNotFoundError(Exception):
    """Raised when a requested dashboard ID does not exist."""
    pass


class VariableValidationError(Exception):
    """Raised when a dashboard variable value is invalid."""
    pass


class DataFetchError(Exception):
    """Raised when one or more panel queries fail during dashboard rendering."""
    pass


class DashboardService:
    """Dashboard configuration management and live data serving.

    This service implements the GetDashboard inbound port by loading
    dashboard configurations from PostgreSQL, substituting dynamic variables,
    executing panel queries in parallel against the time series store, and
    assembling the complete dashboard response with populated data.
    """

    def __init__(
        self,
        time_series_repo: TimeSeriesRepository,
        event_repo: EventRepository,
        cache_ttl_seconds: int = 30,
    ) -> None:
        """Initialize the dashboard service with required dependencies.

        Args:
            time_series_repo: Repository for querying metric time series data.
            event_repo: Repository for dashboard configurations (PostgreSQL).
            cache_ttl_seconds: Time-to-live for cached dashboard data.
                Defaults to 30 seconds for near-real-time dashboards.
        """
        self._time_series_repo = time_series_repo
        self._event_repo = event_repo
        self._cache_ttl = cache_ttl_seconds
        self._cache: dict[str, tuple[datetime, dict]] = {}

    def get_dashboard(
        self,
        dashboard_id: str,
        variables: dict[str, str] | None = None,
        time_range: TimeRange | None = None,
    ) -> dict[str, Any]:
        """Retrieve a dashboard with live data for all panels.

        Loads the dashboard configuration, substitutes dynamic variables,
        and executes all panel queries against the time series store.
        Results are cached for 30 seconds to support frequent refresh
        cycles without overloading the database.

        Args:
            dashboard_id: The unique identifier of the dashboard.
            variables: Optional dynamic variables for query customization.
            time_range: The temporal scope for panel queries. Defaults to
                the last hour.

        Returns:
            A dictionary containing the dashboard definition and populated
            data for each panel.

        Raises:
            DashboardNotFoundError: If the dashboard ID does not exist.
            VariableValidationError: If a variable value is invalid.
            DataFetchError: If panel queries fail.
        """
        cache_key = self._build_cache_key(dashboard_id, variables, time_range)
        cached = self._get_cached_dashboard(cache_key)
        if cached is not None:
            logger.info("Returning cached dashboard: id=%s", dashboard_id)
            return cached

        config = self._event_repo.get_dashboard_config(dashboard_id)
        if config is None:
            raise DashboardNotFoundError(f"Dashboard not found: {dashboard_id}")

        if time_range is None:
            time_range = TimeRange(
                start=datetime.utcnow() - timedelta(hours=1),
                end=datetime.utcnow(),
            )

        if variables:
            self._validate_variables(config, variables)

        panels = config.get("panels", [])
        panel_data: dict[str, Any] = {}

        for panel in panels:
            panel_id = panel.get("panel_id", "")
            try:
                data = self._execute_panel_query(panel, variables, time_range)
                panel_data[panel_id] = data
            except Exception as exc:
                logger.error("Failed to execute panel query: panel_id=%s, error=%s", panel_id, exc)
                panel_data[panel_id] = {"error": str(exc), "data": []}

        result = {
            "dashboard_id": dashboard_id,
            "title": config.get("title", ""),
            "description": config.get("description", ""),
            "panels": panels,
            "data": panel_data,
            "rendered_at": datetime.utcnow().isoformat(),
            "time_range": time_range.to_dict(),
        }

        self._cache_dashboard(cache_key, result)
        return result

    def list_dashboards(self, tag: str | None = None) -> list[dict[str, Any]]:
        """List all available dashboards with optional tag filtering.

        Args:
            tag: Optional tag filter for categorized dashboard navigation.

        Returns:
            A list of dashboard summary dictionaries with ID, title,
            description, and tags.
        """
        return self._event_repo.list_dashboard_configs(tag=tag)

    def update_dashboard(self, dashboard_id: str, config: dict[str, Any]) -> dict[str, Any]:
        """Update a dashboard configuration.

        Validates the new configuration before persisting it. The updated
        configuration takes effect immediately; any cached data for the
        previous configuration is invalidated.

        Args:
            dashboard_id: The unique identifier of the dashboard.
            config: The new dashboard configuration.

        Returns:
            The updated dashboard configuration.

        Raises:
            DashboardNotFoundError: If the dashboard ID does not exist.
        """
        self._validate_dashboard_config(config)
        self._event_repo.save_dashboard_config(dashboard_id, config)
        self._invalidate_cache(dashboard_id)
        logger.info("Updated dashboard configuration: id=%s", dashboard_id)
        return config

    def _execute_panel_query(
        self,
        panel: dict[str, Any],
        variables: dict[str, str] | None,
        time_range: TimeRange,
    ) -> dict[str, Any]:
        """Execute a single panel's metric query with variable substitution.

        Substitutes dashboard variables into the panel's query template,
        then delegates to the time series repository for execution.

        Args:
            panel: The panel configuration dictionary.
            variables: Optional dynamic variables for substitution.
            time_range: The temporal scope for the query.

        Returns:
            A dictionary containing the panel data and metadata.
        """
        query = panel.get("query", {})
        metric_names = query.get("metric_names", [])
        labels = query.get("labels", {})

        if variables:
            metric_names = [self._substitute_variables(name, variables) for name in metric_names]
            labels = {
                k: self._substitute_variables(v, variables) for k, v in labels.items()
            }

        window_str = query.get("window", "1m")
        window = self._parse_window(window_str)
        agg_str = query.get("aggregation", "avg")
        aggregation = self._parse_aggregation(agg_str)

        series = self._time_series_repo.query(
            metric_names=metric_names,
            labels=labels if labels else None,
            time_range=time_range,
            window=window,
            aggregation=aggregation,
        )

        return {
            "panel_type": panel.get("panel_type", "line_chart"),
            "title": panel.get("title", ""),
            "series": [s.to_dict() for s in series],
        }

    def _substitute_variables(self, template: str, variables: dict[str, str]) -> str:
        """Replace variable placeholders in a query template with actual values.

        Variable placeholders are denoted by the pattern ${variable_name}.
        For example, "order.count" with variables {"service": "catalog"}
        would not be modified, but "${service}.request_count" would become
        "catalog.request_count".

        Args:
            template: The string template with potential variable placeholders.
            variables: The variable name-to-value mapping.

        Returns:
            The template with all variable placeholders replaced.
        """
        result = template
        for var_name, var_value in variables.items():
            result = result.replace(f"${{{var_name}}}", var_value)
        return result

    def _validate_variables(self, config: dict[str, Any], variables: dict[str, str]) -> None:
        """Validate that the provided variables match the dashboard's schema.

        Checks that all required variables are provided and that variable
        values match the expected format (if defined in the configuration).

        Args:
            config: The dashboard configuration.
            variables: The provided variable values.

        Raises:
            VariableValidationError: If a required variable is missing or
                a value does not match the expected format.
        """
        defined_vars = config.get("variables", {})
        for var_name, var_def in defined_vars.items():
            if var_def.get("required", False) and var_name not in variables:
                raise VariableValidationError(
                    f"Required variable '{var_name}' is not provided."
                )
            if var_name in variables:
                pattern = var_def.get("validation_pattern")
                if pattern and not re.match(pattern, variables[var_name]):
                    raise VariableValidationError(
                        f"Variable '{var_name}' value '{variables[var_name]}' "
                        f"does not match pattern '{pattern}'."
                    )

    def _validate_dashboard_config(self, config: dict[str, Any]) -> None:
        """Validate the structure of a dashboard configuration.

        Ensures that the configuration contains the required fields and
        that panels have valid query specifications.

        Args:
            config: The dashboard configuration to validate.

        Raises:
            ValueError: If the configuration is invalid.
        """
        if "title" not in config:
            raise ValueError("Dashboard configuration must include a 'title' field.")
        if "panels" not in config:
            raise ValueError("Dashboard configuration must include a 'panels' field.")
        for i, panel in enumerate(config["panels"]):
            if "panel_id" not in panel:
                raise ValueError(f"Panel at index {i} must include a 'panel_id' field.")
            if "query" not in panel:
                raise ValueError(f"Panel '{panel.get('panel_id', i)}' must include a 'query' field.")

    def _parse_window(self, window_str: str) -> AggregationWindow:
        """Parse a window string into an AggregationWindow enum value.

        Args:
            window_str: The window string (e.g., "1m", "5m", "1h", "1d").

        Returns:
            The corresponding AggregationWindow enum value.
        """
        mapping = {
            "1m": AggregationWindow.ONE_MINUTE,
            "5m": AggregationWindow.FIVE_MINUTES,
            "1h": AggregationWindow.ONE_HOUR,
            "1d": AggregationWindow.ONE_DAY,
        }
        return mapping.get(window_str, AggregationWindow.ONE_MINUTE)

    def _parse_aggregation(self, agg_str: str) -> AggregationFunction:
        """Parse an aggregation string into an AggregationFunction enum value.

        Args:
            agg_str: The aggregation function string (e.g., "avg", "sum", "p99").

        Returns:
            The corresponding AggregationFunction enum value.
        """
        mapping = {
            "sum": AggregationFunction.SUM,
            "avg": AggregationFunction.AVG,
            "min": AggregationFunction.MIN,
            "max": AggregationFunction.MAX,
            "count": AggregationFunction.COUNT,
            "p50": AggregationFunction.P50,
            "p95": AggregationFunction.P95,
            "p99": AggregationFunction.P99,
        }
        return mapping.get(agg_str, AggregationFunction.AVG)

    def _build_cache_key(
        self,
        dashboard_id: str,
        variables: dict[str, str] | None,
        time_range: TimeRange | None,
    ) -> str:
        """Build a deterministic cache key for dashboard data deduplication.

        Args:
            dashboard_id: The dashboard identifier.
            variables: The variable substitutions.
            time_range: The time range.

        Returns:
            A string cache key.
        """
        var_str = str(sorted(variables.items())) if variables else ""
        tr_str = f"{time_range.start.isoformat()}-{time_range.end.isoformat()}" if time_range else "default"
        return f"{dashboard_id}:{tr_str}:{var_str}"

    def _get_cached_dashboard(self, cache_key: str) -> dict | None:
        """Retrieve a cached dashboard if it exists and has not expired.

        Args:
            cache_key: The cache key to look up.

        Returns:
            The cached dashboard data if valid, or None.
        """
        entry = self._cache.get(cache_key)
        if entry is None:
            return None

        cached_at, data = entry
        if (datetime.utcnow() - cached_at).total_seconds() > self._cache_ttl:
            del self._cache[cache_key]
            return None

        return data

    def _cache_dashboard(self, cache_key: str, data: dict) -> None:
        """Store rendered dashboard data in the cache.

        Args:
            cache_key: The cache key for the dashboard.
            data: The rendered dashboard data.
        """
        self._cache[cache_key] = (datetime.utcnow(), data)

    def _invalidate_cache(self, dashboard_id: str) -> None:
        """Invalidate all cached entries for a specific dashboard.

        Called when a dashboard configuration is updated to ensure that
        subsequent requests return fresh data based on the new configuration.

        Args:
            dashboard_id: The dashboard to invalidate.
        """
        keys_to_remove = [k for k in self._cache if k.startswith(f"{dashboard_id}:")]
        for key in keys_to_remove:
            del self._cache[key]
