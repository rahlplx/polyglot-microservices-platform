// ---------------------------------------------------------------------------
// Inbound Port: Attestation Use Case Trait
// ---------------------------------------------------------------------------
// Defines the attestation use case interface. This is the primary
// inbound port for workload identity verification. ZERO external
// dependencies — only std and domain models are used.
// ---------------------------------------------------------------------------

use crate::domain::models::{AttestationRequest, AttestationResult};

/// The attestation use case trait.
///
/// This trait defines the interface for workload attestation, which is
/// the process of verifying a workload's identity based on its runtime
/// properties (selectors). Attestation is the foundation of the SPIFFE
/// identity model: a workload must be attested before it can receive
/// an SVID.
///
/// Implementations of this trait are provided by the domain services
/// layer, and consumers are the inbound adapters (gRPC handlers).
pub trait AttestationUseCase: Send + Sync {
    /// Attest a workload based on its claimed identity and selectors.
    ///
    /// The attestation process:
    /// 1. Validates that the SPIFFE ID is well-formed
    /// 2. Checks that the SPIFFE ID belongs to the specified trust domain
    /// 3. Looks up registered workloads matching the SPIFFE ID
    /// 4. Verifies that the presented selectors match the registered workload
    /// 5. Returns the attestation result with expiry timestamp
    ///
    /// # Errors
    /// Returns an error if the attestation process encounters an
    /// internal failure (database unavailable, etc.).
    fn attest(&self, request: AttestationRequest) -> Result<AttestationResult, AttestationError>;
}

/// Errors that can occur during attestation.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum AttestationError {
    /// The workload store is unavailable.
    StoreUnavailable(String),
    /// An internal error occurred.
    Internal(String),
}

impl std::fmt::Display for AttestationError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::StoreUnavailable(detail) => {
                write!(f, "workload store unavailable: {}", detail)
            }
            Self::Internal(detail) => {
                write!(f, "internal attestation error: {}", detail)
            }
        }
    }
}

impl std::error::Error for AttestationError {}
