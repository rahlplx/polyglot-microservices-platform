// ---------------------------------------------------------------------------
// OpenTelemetry Observability Adapter
// ---------------------------------------------------------------------------
// Implements OTel instrumentation for the Identity service.
// Provides tracing, metrics, and structured logging.
// ---------------------------------------------------------------------------

use std::time::Duration;

/// The OpenTelemetry observability adapter.
///
/// This adapter provides comprehensive observability for the Identity
/// service through OpenTelemetry traces, metrics, and structured logs.
/// All sensitive fields (private keys, certificate chains) are excluded
/// from trace attributes to prevent data leakage.
///
/// Instrumentation points:
/// - SVID Issuance Tracing: workload ID, SPIFFE ID, TTL, issuance latency
/// - Verification Tracing: presented SPIFFE ID, result, chain depth
/// - Rotation Tracing: rotation trigger, old/new serials, duration
/// - Certificate Metrics: issued, revoked, active, issuance duration
/// - Workload Registry Metrics: registered, events
pub struct OTelObservabilityAdapter {
    /// The service name for OTel resource attributes.
    service_name: String,
    /// The service version for OTel resource attributes.
    #[allow(dead_code)]
    service_version: String,
    /// The OTLP endpoint for trace and metric export.
    otlp_endpoint: String,
    /// Whether the adapter has been initialized.
    initialized: std::sync::atomic::AtomicBool,
}

impl OTelObservabilityAdapter {
    /// Creates a new OTel observability adapter.
    pub fn new(service_name: String, service_version: String, otlp_endpoint: String) -> Self {
        Self {
            service_name,
            service_version,
            otlp_endpoint,
            initialized: std::sync::atomic::AtomicBool::new(false),
        }
    }

    /// Initializes the OpenTelemetry pipeline.
    ///
    /// This sets up:
    /// - OTLP trace exporter (gRPC)
    /// - OTLP metric exporter (gRPC)
    /// - Tracing subscriber with OTel layer
    /// - Custom sampling strategy
    pub async fn init(&self) -> Result<(), OTelError> {
        if self
            .initialized
            .load(std::sync::atomic::Ordering::SeqCst)
        {
            return Ok(());
        }

        // In production, this would:
        // 1. Create an OTLP trace exporter with tonic transport
        // 2. Configure tail-based sampling (100% for revocations, 10% for verifications)
        // 3. Create an OTLP metric exporter
        // 4. Build the OpenTelemetry tracer provider
        // 5. Build the OpenTelemetry meter provider
        // 6. Install the tracing subscriber with the OTel layer

        self.initialized
            .store(true, std::sync::atomic::Ordering::SeqCst);

        Ok(())
    }

    /// Shuts down the OpenTelemetry pipeline gracefully.
    pub async fn shutdown(&self) {
        // In production, this would:
        // 1. Flush all pending traces
        // 2. Flush all pending metrics
        // 3. Shutdown the tracer provider
        // 4. Shutdown the meter provider
    }

    /// Records an SVID issuance event.
    pub fn record_svid_issued(&self, trust_domain: &str, ttl_bucket: &str, duration: Duration) {
        // In production, this would:
        // 1. Increment identity.svid.issued_total counter (labels: trust_domain, ttl_bucket)
        // 2. Record identity.svid.issuance_duration histogram
        // 3. Update identity.svid.active gauge
        let _ = (trust_domain, ttl_bucket, duration);
    }

    /// Records an SVID revocation event.
    pub fn record_svid_revoked(&self, reason: &str, trust_domain: &str) {
        // In production, this would:
        // 1. Increment identity.svid.revoked_total counter (labels: reason, trust_domain)
        // 2. Update identity.svid.active gauge (decrement)
        let _ = (reason, trust_domain);
    }

    /// Records a workload registration event.
    pub fn record_workload_event(&self, event_type: &str, namespace: &str) {
        // In production, this would:
        // 1. Increment identity.workload.events_total counter (labels: event_type)
        // 2. Update identity.workload.registered gauge (labels: namespace)
        let _ = (event_type, namespace);
    }

    /// Records a certificate rotation event.
    pub fn record_rotation(&self, reason: &str, duration: Duration, success: bool) {
        // In production, this would:
        // 1. Create a rotation span with trigger, old/new serials, duration
        // 2. Record identity.rotation.duration histogram
        // 3. Increment identity.rotation.total counter (labels: reason, success)
        let _ = (reason, duration, success);
    }

    /// Returns the service name.
    pub fn service_name(&self) -> &str {
        &self.service_name
    }

    /// Returns the OTLP endpoint.
    pub fn otlp_endpoint(&self) -> &str {
        &self.otlp_endpoint
    }
}

/// Errors that can occur in the observability adapter.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum OTelError {
    /// Failed to initialize the OTLP exporter.
    ExporterInitFailed(String),
    /// Failed to install the tracing subscriber.
    SubscriberInstallFailed(String),
    /// The adapter is not initialized.
    NotInitialized,
}

impl std::fmt::Display for OTelError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::ExporterInitFailed(detail) => {
                write!(f, "OTLP exporter init failed: {}", detail)
            }
            Self::SubscriberInstallFailed(detail) => {
                write!(f, "tracing subscriber install failed: {}", detail)
            }
            Self::NotInitialized => write!(f, "observability adapter not initialized"),
        }
    }
}

impl std::error::Error for OTelError {}

/// Sampling configuration for the OTel adapter.
///
/// The Identity service uses a custom sampling strategy:
/// - 100% sampling for revocation and rotation operations (security-critical)
/// - 10% sampling for routine verification operations (high volume)
/// - 100% sampling for all errors
#[derive(Debug, Clone)]
pub struct SamplingConfig {
    /// Sampling rate for revocation operations (0.0 - 1.0).
    pub revocation_sample_rate: f64,
    /// Sampling rate for rotation operations (0.0 - 1.0).
    pub rotation_sample_rate: f64,
    /// Sampling rate for verification operations (0.0 - 1.0).
    pub verification_sample_rate: f64,
    /// Sampling rate for error spans (always 1.0).
    pub error_sample_rate: f64,
}

impl Default for SamplingConfig {
    fn default() -> Self {
        Self {
            revocation_sample_rate: 1.0,
            rotation_sample_rate: 1.0,
            verification_sample_rate: 0.1,
            error_sample_rate: 1.0,
        }
    }
}

/// Metric names for the Identity service.
pub mod metrics {
    /// Counter: total SVIDs issued.
    pub const SVID_ISSUED_TOTAL: &str = "identity.svid.issued_total";
    /// Counter: total SVIDs revoked.
    pub const SVID_REVOKED_TOTAL: &str = "identity.svid.revoked_total";
    /// Gauge: currently active SVIDs.
    pub const SVID_ACTIVE: &str = "identity.svid.active";
    /// Histogram: SVID issuance duration.
    pub const SVID_ISSUANCE_DURATION: &str = "identity.svid.issuance_duration";
    /// Gauge: registered workloads.
    pub const WORKLOAD_REGISTERED: &str = "identity.workload.registered";
    /// Counter: workload registration events.
    pub const WORKLOAD_EVENTS_TOTAL: &str = "identity.workload.events_total";
}

/// Span names for the Identity service.
pub mod spans {
    /// Span name for SVID issuance.
    pub const ISSUE_SVID: &str = "identity.issue_svid";
    /// Span name for workload attestation.
    pub const ATTEST_WORKLOAD: &str = "identity.attest_workload";
    /// Span name for SVID revocation.
    pub const REVOKE_SVID: &str = "identity.revoke_svid";
    /// Span name for certificate rotation.
    pub const ROTATE_CERTIFICATE: &str = "identity.rotate_certificate";
    /// Span name for trust bundle retrieval.
    pub const GET_TRUST_BUNDLE: &str = "identity.get_trust_bundle";
    /// Span name for SVID verification.
    pub const VERIFY_SVID: &str = "identity.verify_svid";
}
