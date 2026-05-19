// ---------------------------------------------------------------------------
// Observability Adapter Module
// ---------------------------------------------------------------------------

pub mod otel;

pub use otel::{OTelObservabilityAdapter, OTelError, SamplingConfig};
