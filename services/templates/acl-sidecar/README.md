# ACL Sidecar Template

## Overview

The Anti-Corruption Layer (ACL) sidecar is a mandatory infrastructure component for any service that communicates with external or third-party systems. It acts as a proxy between the service's core business logic and the external system, providing circuit breaking, retry with jitter, rate limiting, and proprietary import blocking. The sidecar ensures that the service's domain model remains isolated from external system conventions and that vendor lock-in is confined to the sidecar's translation layer.

## When to Use an ACL Sidecar

An ACL sidecar is mandatory in the following scenarios:

1. **External Payment Gateways**: Any communication with third-party payment processors (Stripe, Adyen, Braintree) must go through an ACL sidecar. This is non-negotiable because payment gateways have proprietary SDKs, rate limits, and failure modes that must not leak into the service's core logic.

2. **External Notification Providers**: Communication with email providers (SendGrid, Mailgun), SMS providers (Twilio, Vonage), and push notification services (Firebase, APNS) should use an ACL sidecar to isolate the service from vendor-specific API formats and authentication mechanisms.

3. **External Shipping Carriers**: Integration with shipping carriers (FedEx, UPS, DHL) that use proprietary APIs, EDI formats, or SOAP protocols must use an ACL sidecar to translate between the domain model and the carrier's format.

4. **Third-Party Analytics Platforms**: If the Analytics service needs to export data to external platforms (Mixpanel, Amplitude, Segment), the export should go through an ACL sidecar to prevent vendor-specific data schemas from contaminating the internal data model.

5. **Any SaaS API Integration**: Any integration with a Software-as-a-Service API that is not under the organization's control should use an ACL sidecar, as the API's contract may change without notice and the service's domain model must be protected from such changes.

An ACL sidecar is NOT required for:

- Internal service-to-service communication (use mTLS with SPIFFE SVIDs)
- Communication with internal infrastructure (PostgreSQL, Kafka, Redis, ClickHouse)
- Communication with the Schema Registry or Identity service
- Read-only access to internal monitoring endpoints

## Configuration Structure

The ACL sidecar is configured via a YAML file (`sidecar-config.yaml`) that is mounted into the sidecar container. The configuration is divided into five sections:

1. **Circuit Breaker**: Controls when the circuit opens (stops forwarding requests) and when it resets. The circuit breaker prevents cascading failures when the external system is degraded or unavailable.

2. **Retry Policy**: Controls how failed requests are retried, including the maximum number of retries, backoff strategy, and jitter range. The retry policy ensures that transient failures do not cause permanent request loss.

3. **Rate Limiting**: Controls the maximum request rate to the external system, ensuring that the service stays within the external system's API rate limits and does not trigger throttling or account suspension.

4. **Package Patterns**: Controls which import patterns are allowed and blocked in the service's source code. This prevents proprietary vendor SDKs from being imported directly into the service's core logic, ensuring that the sidecar is the only integration point.

5. **Health Check Endpoints**: The sidecar exposes three endpoints for Kubernetes integration: `/health` (liveness probe), `/ready` (readiness probe), and `/metrics` (Prometheus-format metrics). The `/health` endpoint returns a 200 status if the sidecar process is running. The `/ready` endpoint returns a 200 status if the sidecar is operational and the external system is reachable (unless the circuit breaker is open, in which case readiness still returns 200 since the sidecar itself is healthy). The `/metrics` endpoint exposes Prometheus-format metrics including circuit breaker state, request counts, latency histograms, and rate limiter statistics.

## Circuit Breaker Settings

The circuit breaker implements the three-state model: CLOSED (normal operation), OPEN (all requests fail fast), and HALF-OPEN (limited requests to test recovery).

- **Failure Rate Threshold**: The percentage of failures within the metrics window that triggers the circuit to open. Default: 50% (0.5). When more than half of the requests within the rolling window fail, the circuit opens. This complements the consecutive failure threshold by catching gradual degradation patterns that individual consecutive failures might miss.

- **Failure Threshold**: The number of consecutive failures required to open the circuit as a fast-path trigger. Default: 5 consecutive failures. This provides rapid circuit opening for burst failure scenarios even before the failure rate threshold is calculated across the full metrics window.

- **Reset Timeout**: The duration the circuit stays open before transitioning to HALF-OPEN. Default: 30 seconds. This should be long enough for the external system to recover but short enough to minimize the window of unavailability. For payment gateways, 30 seconds is appropriate; for less critical integrations, 60 seconds may be acceptable.

- **Half-Open Max Requests**: The number of test requests allowed through in HALF-OPEN state. Default: 3 requests. If all test requests succeed, the circuit transitions to CLOSED. If any test request fails, the circuit transitions back to OPEN.

- **Success Threshold**: The number of consecutive successful requests required in HALF-OPEN state to transition to CLOSED. Default: 3 consecutive successes. This should be set to at least 2 to avoid flapping due to a single coincidental success.

- **Metrics Window**: The rolling time window for tracking failure rates. Default: 60 seconds. The circuit breaker tracks failures within this window to determine if the failure threshold has been exceeded.

## Proprietary Import Blocking Rules

The ACL sidecar enforces a zero-tolerance policy on proprietary imports. The service's source code must never directly import or reference vendor-specific packages, SDKs, or client libraries. All vendor-specific code must reside within the sidecar's translation layer.

The blocking rules are enforced at two levels:

1. **Pre-commit Hook**: A Git pre-commit hook that scans staged files for blocked import patterns. If a blocked pattern is detected, the commit is rejected with a clear error message explaining why the import is blocked and how to use the ACL sidecar instead. This provides immediate feedback during development.

2. **CI Pipeline Check**: A CI pipeline step that scans the entire repository for blocked import patterns. This serves as a safety net in case a developer bypasses the pre-commit hook. The CI check fails the build if any blocked patterns are detected.

The import patterns are configured as regular expressions in the sidecar configuration file. The default patterns block imports from common payment and notification provider SDKs, but additional patterns can be added for any vendor.

## Pre-commit Hook Integration

To install the pre-commit hook, add the following to the service's `.pre-commit-config.yaml`:

```yaml
repos:
  - repo: local
    hooks:
      - id: acl-import-check
        name: ACL Import Check
        entry: acl-sidecar check-imports --config sidecar-config.yaml
        language: system
        types: [python, java, go, typescript]
        pass_filenames: true
```

The hook reads the `allowed_patterns` and `blocked_patterns` from the sidecar configuration and scans each staged file for matching import statements. If a blocked pattern is found, the hook outputs the file name, line number, and the matched pattern, and exits with a non-zero status to block the commit.

## Deployment Architecture

The ACL sidecar is deployed as a Kubernetes sidecar container in the same pod as the service. This co-location provides several benefits:

- **Shared Network Namespace**: The sidecar and service share the same network namespace, allowing the sidecar to proxy requests on localhost without network overhead.
- **Shared Lifecycle**: The sidecar and service start and stop together, ensuring that the proxy is always available when the service is running.
- **Resource Isolation**: The sidecar has its own resource limits (CPU, memory) independent of the service, preventing the sidecar from consuming resources needed by the service.

The service communicates with the sidecar over localhost using a simple HTTP or gRPC interface. The sidecar translates the domain-oriented request into the vendor-specific API format and forwards it to the external system. The response is translated back into the domain format and returned to the service.

## Example: Payment Service with ACL Sidecar

```
[Order Service] --gRPC--> [Payment Service] --localhost:8443--> [ACL Sidecar] --HTTPS--> [Stripe API]
```

The Payment Service sends a `ProcessPaymentRequest` to the ACL sidecar on localhost:8443. The sidecar translates the request into Stripe's `POST /v1/charges` API format, adds the Stripe API key from its secure secret store, and forwards the request. The Stripe response is translated back into a `ProcessPaymentResponse` and returned to the Payment Service. The Payment Service never sees the Stripe API format or imports the Stripe SDK.
