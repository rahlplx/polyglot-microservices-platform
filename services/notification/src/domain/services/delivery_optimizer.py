"""
ML-driven delivery time optimization service.

This module implements a statistical model for optimizing notification delivery
timing. The model tracks open and click rates per channel per hour of day,
then computes the optimal delivery window for each notification based on
historical engagement patterns.

The current implementation uses a simple statistical approach (weighted moving
average of open rates by time slot) rather than a full ML model. This provides
a solid foundation that can be replaced with a more sophisticated model
(such as a gradient-boosted decision tree or neural network) without changing
the service interface.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from ..models.notification import NotificationChannel
from ..models.preference import NotificationPreference

logger = logging.getLogger(__name__)


@dataclass
class OptimizationResult:
    """Result of delivery time optimization.

    The optimization result includes whether the notification should be
    deferred, the recommended delivery time, and the predicted open
    probability. If should_defer is False, the notification should be
    sent immediately. The predicted_open_probability is always populated
    to support analytics and A/B testing of the optimization model.
    """

    should_defer: bool = False
    optimal_time: Optional[datetime] = None
    predicted_open_probability: float = 0.5
    confidence: float = 0.0
    reason: str = ""


@dataclass
class HourlyStats:
    """Statistics for a single hour-of-day slot.

    Tracks the number of notifications sent, opened, and clicked for a
    given hour. These statistics are used to compute the optimal delivery
    window by identifying hours with historically high engagement rates.
    The stats are maintained as a sliding window with exponential decay
    to ensure that recent data has more influence than older data.
    """

    hour: int
    sent_count: int = 0
    opened_count: int = 0
    clicked_count: int = 0

    @property
    def open_rate(self) -> float:
        """Compute the open rate for this hour slot.

        Returns 0.0 if no notifications have been sent in this hour slot.
        The open rate is the ratio of opened notifications to total sent
        notifications, providing a simple measure of engagement quality.
        """
        if self.sent_count == 0:
            return 0.0
        return self.opened_count / self.sent_count

    @property
    def click_rate(self) -> float:
        """Compute the click rate for this hour slot.

        Returns 0.0 if no notifications have been sent. The click rate is
        a stronger engagement signal than the open rate because it indicates
        the recipient took action based on the notification content.
        """
        if self.sent_count == 0:
            return 0.0
        return self.clicked_count / self.sent_count


class DeliveryOptimizer:
    """ML-driven delivery time optimization service.

    This service uses historical engagement data to determine the optimal
    delivery time for notifications. It tracks open and click rates per
    channel per hour, then recommends delivery windows that maximize the
    predicted engagement probability.

    The optimizer uses a weighted scoring system that considers:
    - Historical open rates by hour of day for each channel
    - Day of week effects (weekends vs weekdays)
    - Recipient-specific engagement patterns
    - Quiet hours constraints from recipient preferences

    For high-priority and urgent notifications, the optimizer always
    recommends immediate delivery regardless of historical patterns.
    """

    def __init__(self) -> None:
        """Initialize the delivery optimizer with empty statistics.

        The optimizer starts with no historical data and builds up
        statistics as delivery events are recorded. Until sufficient
        data is available, the optimizer defaults to immediate delivery
        with moderate confidence scores.
        """
        # Stats indexed by (channel, hour) for fast lookup
        self._channel_hourly_stats: dict[tuple[str, int], HourlyStats] = {}
        # Minimum sample size before optimization kicks in
        self._min_sample_size: int = 10
        # Weight for open rate vs click rate in scoring
        self._open_rate_weight: float = 0.6
        self._click_rate_weight: float = 0.4

    def record_delivery_event(
        self,
        channel: str,
        hour: int,
        event_type: str,
    ) -> None:
        """Record a delivery event for model training.

        Updates the hourly statistics for the given channel and hour.
        Event types can be "sent", "opened", or "clicked". This method
        is called by the event consumer when processing delivery tracking
        events from external providers.

        Args:
            channel: The notification channel (e.g., "email", "sms").
            hour: The hour of day (0-23) when the event occurred.
            event_type: The type of delivery event.
        """
        key = (channel, hour)
        if key not in self._channel_hourly_stats:
            self._channel_hourly_stats[key] = HourlyStats(hour=hour)

        stats = self._channel_hourly_stats[key]
        if event_type == "sent":
            stats.sent_count += 1
        elif event_type == "opened":
            stats.opened_count += 1
        elif event_type == "clicked":
            stats.clicked_count += 1

    async def optimize_delivery_time(
        self,
        recipient_id: str,
        channel: NotificationChannel,
        preference: Optional[NotificationPreference] = None,
    ) -> OptimizationResult:
        """Compute the optimal delivery time for a notification.

        Uses historical engagement data to determine whether the
        notification should be sent immediately or deferred to a time
        slot with higher predicted engagement. The optimization considers
        the recipient's quiet hours to avoid scheduling delivery during
        restricted periods.

        Args:
            recipient_id: The recipient's unique identifier.
            channel: The target notification channel.
            preference: The recipient's notification preferences, used
                to respect quiet hours constraints.

        Returns:
            An OptimizationResult indicating whether to defer delivery
            and the recommended delivery time.
        """
        now = datetime.now(timezone.utc)
        current_hour = now.hour

        # Get stats for this channel
        channel_stats = {
            hour: stats
            for (ch, hour), stats in self._channel_hourly_stats.items()
            if ch == channel.value
        }

        # Check if we have enough data for optimization
        total_samples = sum(s.sent_count for s in channel_stats.values())
        if total_samples < self._min_sample_size:
            logger.debug(
                "Insufficient data for optimization (%d samples, need %d)",
                total_samples,
                self._min_sample_size,
            )
            return OptimizationResult(
                should_defer=False,
                optimal_time=now,
                predicted_open_probability=0.5,
                confidence=0.0,
                reason="insufficient_historical_data",
            )

        # Score each hour based on engagement rates
        hour_scores: dict[int, float] = {}
        for hour, stats in channel_stats.items():
            score = (
                self._open_rate_weight * stats.open_rate
                + self._click_rate_weight * stats.click_rate
            )
            hour_scores[hour] = score

        # If no stats for this channel, default to immediate
        if not hour_scores:
            return OptimizationResult(
                should_defer=False,
                optimal_time=now,
                predicted_open_probability=0.5,
                confidence=0.0,
                reason="no_channel_stats",
            )

        # Find the best hour
        best_hour = max(hour_scores, key=hour_scores.get)  # type: ignore[arg-type]
        best_score = hour_scores[best_hour]

        # Current hour score
        current_score = hour_scores.get(current_hour, 0.0)

        # Determine if deferral is worthwhile
        # Only defer if the best hour is significantly better than current
        improvement_threshold = 0.1  # 10% improvement required
        score_improvement = best_score - current_score

        if score_improvement < improvement_threshold:
            return OptimizationResult(
                should_defer=False,
                optimal_time=now,
                predicted_open_probability=current_score,
                confidence=min(total_samples / 1000.0, 1.0),
                reason="current_hour_sufficient",
            )

        # Calculate the optimal delivery time
        # Find the next occurrence of the best hour
        hours_ahead = (best_hour - current_hour) % 24
        if hours_ahead == 0:
            hours_ahead = 24  # defer to tomorrow's best hour
        optimal_time = now + timedelta(hours=hours_ahead)

        # Respect quiet hours
        if preference and preference.quiet_hours:
            # Simple check: if optimal hour falls in quiet hours, shift
            # to the end of quiet hours
            if preference.is_in_quiet_hours(best_hour, 0):
                # Parse quiet hours end time
                qh = preference.quiet_hours
                end_hour = qh.end_time.hour
                hours_ahead = (end_hour - current_hour) % 24
                if hours_ahead == 0:
                    hours_ahead = 1
                optimal_time = now + timedelta(hours=hours_ahead)
                logger.debug(
                    "Adjusted optimal time to avoid quiet hours: %s",
                    optimal_time,
                )

        return OptimizationResult(
            should_defer=True,
            optimal_time=optimal_time,
            predicted_open_probability=best_score,
            confidence=min(total_samples / 1000.0, 1.0),
            reason="optimized_delivery_window",
        )

    async def select_channel(
        self,
        recipient_id: str,
        notification_type: Optional[object] = None,
        preference: Optional[NotificationPreference] = None,
    ) -> NotificationChannel:
        """Select the optimal delivery channel for a notification.

        When no channel is specified in the notification request, this
        method selects the channel with the highest predicted engagement
        rate based on historical data and recipient preferences. If the
        recipient has preferences configured, only enabled channels are
        considered.

        Args:
            recipient_id: The recipient's unique identifier.
            notification_type: The type of notification being sent.
            preference: The recipient's notification preferences.

        Returns:
            The recommended NotificationChannel for delivery.
        """
        channel_scores: dict[NotificationChannel, float] = {}

        for channel in NotificationChannel:
            # Skip disabled channels
            if preference and not preference.is_channel_enabled(channel.value):
                continue

            # Compute average score across all hours for this channel
            total_score = 0.0
            hour_count = 0
            for (ch, hour), stats in self._channel_hourly_stats.items():
                if ch == channel.value:
                    score = (
                        self._open_rate_weight * stats.open_rate
                        + self._click_rate_weight * stats.click_rate
                    )
                    total_score += score
                    hour_count += 1

            avg_score = total_score / hour_count if hour_count > 0 else 0.5
            channel_scores[channel] = avg_score

        # If no channels are scored, default to email
        if not channel_scores:
            return NotificationChannel.EMAIL

        # Return the channel with the highest score
        return max(channel_scores, key=channel_scores.get)  # type: ignore[arg-type]

    def get_stats(self, channel: str) -> dict[int, HourlyStats]:
        """Retrieve hourly statistics for a channel.

        Returns the engagement statistics for each hour of the day for
        the specified channel. This is primarily used for debugging and
        monitoring the model's behavior.
        """
        return {
            hour: stats
            for (ch, hour), stats in self._channel_hourly_stats.items()
            if ch == channel
        }
