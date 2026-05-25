// ---------------------------------------------------------------------------
// Domain Models Module
// ---------------------------------------------------------------------------
// Core domain models with ZERO external dependencies.
// All models are pure data structures and value objects.
// ---------------------------------------------------------------------------

pub mod attestation;
pub mod svid;
pub mod workload;

// Re-export primary types for convenience
pub use attestation::{
    AttestationFailureReason, AttestationRequest, AttestationResult,
};
pub use svid::{
    RevocationReason, RevocationStatus, RevokedSVID, RotationReason, RotationResult, TTLPolicy,
    TTLPolicyError, X509Bundle, X509SVID,
};
pub use workload::{
    Selector, SelectorError, SPIFFEID, SPIFFEIDError, TrustDomain, Workload,
};
