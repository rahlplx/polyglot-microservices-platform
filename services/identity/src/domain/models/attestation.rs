// ---------------------------------------------------------------------------
// Domain Models: Attestation, AttestationResult
// ---------------------------------------------------------------------------
// This module contains attestation-related domain models.
// ZERO external dependencies — only std is used.
// ---------------------------------------------------------------------------

use super::workload::{Selector, TrustDomain, SPIFFEID};

/// An attestation request from a workload.
///
/// When a workload needs to prove its identity, it initiates an
/// attestation request with its SPIFFE ID, a set of selectors
/// collected from the runtime environment, and its trust domain.
/// The Identity service verifies that the presented selectors
/// match a registered workload entry.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AttestationRequest {
    /// The SPIFFE ID the workload claims to have.
    pub spiffe_id: SPIFFEID,
    /// Selectors collected from the workload's runtime environment.
    pub selectors: Vec<Selector>,
    /// The trust domain the workload belongs to.
    pub trust_domain: TrustDomain,
}

impl AttestationRequest {
    /// Creates a new attestation request.
    pub fn new(spiffe_id: SPIFFEID, selectors: Vec<Selector>, trust_domain: TrustDomain) -> Self {
        Self {
            spiffe_id,
            selectors,
            trust_domain,
        }
    }
}

/// The result of a workload attestation.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AttestationResult {
    /// Whether the attestation succeeded.
    pub attested: bool,
    /// The verified SPIFFE ID (may differ from the requested one if
    /// the attestation process resolved aliases).
    pub spiffe_id: SPIFFEID,
    /// The timestamp (Unix epoch seconds) when this attestation expires.
    /// Attestations are valid for a limited time to prevent replay attacks.
    pub expires_at: u64,
    /// The reason for attestation failure, if applicable.
    pub failure_reason: Option<AttestationFailureReason>,
}

impl AttestationResult {
    /// Creates a successful attestation result.
    pub fn success(spiffe_id: SPIFFEID, expires_at: u64) -> Self {
        Self {
            attested: true,
            spiffe_id,
            expires_at,
            failure_reason: None,
        }
    }

    /// Creates a failed attestation result.
    pub fn failure(spiffe_id: SPIFFEID, reason: AttestationFailureReason) -> Self {
        Self {
            attested: false,
            spiffe_id,
            expires_at: 0,
            failure_reason: Some(reason),
        }
    }
}

/// Reasons why attestation can fail.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum AttestationFailureReason {
    /// No registered workload matches the presented selectors.
    NoMatchingWorkload,
    /// The presented selectors do not fully match the registered workload.
    SelectorMismatch,
    /// The SPIFFE ID does not belong to the specified trust domain.
    TrustDomainMismatch,
    /// The workload has been deregistered.
    WorkloadDeregistered,
    /// The attestation request contains invalid selectors.
    InvalidSelectors(String),
    /// An internal error occurred during attestation.
    InternalError(String),
}

impl std::fmt::Display for AttestationFailureReason {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::NoMatchingWorkload => {
                write!(f, "no registered workload matches the presented selectors")
            }
            Self::SelectorMismatch => write!(
                f,
                "presented selectors do not match the registered workload"
            ),
            Self::TrustDomainMismatch => {
                write!(f, "SPIFFE ID does not belong to the specified trust domain")
            }
            Self::WorkloadDeregistered => write!(f, "workload has been deregistered"),
            Self::InvalidSelectors(detail) => write!(f, "invalid selectors: {}", detail),
            Self::InternalError(detail) => write!(f, "internal error: {}", detail),
        }
    }
}

impl std::error::Error for AttestationFailureReason {}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn attestation_result_success() {
        let spiffe_id = SPIFFEID::parse("spiffe://trust.example.org/services/gateway").unwrap();
        let result = AttestationResult::success(spiffe_id.clone(), 3600);
        assert!(result.attested);
        assert_eq!(result.spiffe_id, spiffe_id);
        assert!(result.failure_reason.is_none());
    }

    #[test]
    fn attestation_result_failure() {
        let spiffe_id = SPIFFEID::parse("spiffe://trust.example.org/services/gateway").unwrap();
        let result =
            AttestationResult::failure(spiffe_id, AttestationFailureReason::NoMatchingWorkload);
        assert!(!result.attested);
        assert!(result.failure_reason.is_some());
    }
}
