// ---------------------------------------------------------------------------
// Inbound Ports: Use Case Traits
// ---------------------------------------------------------------------------
// These traits define the interfaces that inbound adapters (gRPC handlers,
// event consumers) call into. They represent the use cases of the
// Identity service. ZERO external dependencies.
// ---------------------------------------------------------------------------

pub mod attestation;

use crate::domain::models::{
    RevocationReason, RevokedSVID,
    RotationReason, RotationResult, X509Bundle, X509SVID,
};

pub use attestation::AttestationUseCase;

/// The issue SVID use case trait.
///
/// Issues a new X.509 SVID for an attested workload. This is the
/// core operation of the Identity service — every workload in the
/// mesh calls this (typically via the SPIRE Agent) to obtain its
/// identity certificate.
pub trait IssueSVIDUseCase: Send + Sync {
    /// Issue a new X.509 SVID for the given workload.
    ///
    /// # Arguments
    /// * `spiffe_id` - The SPIFFE ID to embed in the SVID
    /// * `ttl_seconds` - Requested TTL (will be capped by policy)
    /// * `dns_names` - DNS names to include in the SAN
    /// * `trust_domain` - The trust domain for the SVID
    /// * `csr_der` - Optional DER-encoded CSR; if not provided,
    ///   the service generates a key pair internally
    ///
    /// # Errors
    /// Returns an error if the workload is not registered or
    /// attested, the TTL exceeds policy, or the CA is unavailable.
    fn issue_svid(
        &self,
        spiffe_id: &str,
        ttl_seconds: u64,
        dns_names: &[String],
        trust_domain: &str,
        csr_der: Option<&[u8]>,
    ) -> Result<(X509SVID, X509Bundle), IssueSVIDError>;
}

/// Errors that can occur during SVID issuance.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum IssueSVIDError {
    /// The workload is not registered in the workload store.
    WorkloadNotFound(String),
    /// The workload is not attested.
    WorkloadNotAttested(String),
    /// The requested TTL exceeds the policy maximum.
    TTLExceededPolicy { requested: u64, maximum: u64 },
    /// The CA signing key is unavailable.
    SigningKeyUnavailable(String),
    /// The SPIFFE ID is invalid.
    InvalidSPIFFEID(String),
    /// The CSR is invalid.
    InvalidCSR(String),
    /// An internal error occurred.
    Internal(String),
}

impl std::fmt::Display for IssueSVIDError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::WorkloadNotFound(id) => write!(f, "workload not found: {}", id),
            Self::WorkloadNotAttested(id) => write!(f, "workload not attested: {}", id),
            Self::TTLExceededPolicy { requested, maximum } => {
                write!(f, "requested TTL {}s exceeds maximum {}s", requested, maximum)
            }
            Self::SigningKeyUnavailable(detail) => write!(f, "signing key unavailable: {}", detail),
            Self::InvalidSPIFFEID(detail) => write!(f, "invalid SPIFFE ID: {}", detail),
            Self::InvalidCSR(detail) => write!(f, "invalid CSR: {}", detail),
            Self::Internal(detail) => write!(f, "internal error: {}", detail),
        }
    }
}

impl std::error::Error for IssueSVIDError {}

/// The revoke SVID use case trait.
///
/// Revokes a previously issued SVID, adding it to the Certificate
/// Revocation List. Emergency revocations (key compromise, CA
/// compromise) bypass approval workflows and are processed immediately.
pub trait RevokeSVIDUseCase: Send + Sync {
    /// Revoke an SVID by serial number.
    ///
    /// # Arguments
    /// * `serial_number` - The serial number of the certificate to revoke
    /// * `reason` - The reason for revocation
    /// * `comment` - Optional comment about the revocation
    /// * `revoked_by` - The identity that performed the revocation
    /// * `trust_domain` - The trust domain of the SVID
    ///
    /// # Errors
    /// Returns an error if the certificate is not found,
    /// already revoked, or the store is unavailable.
    fn revoke_svid(
        &self,
        serial_number: &str,
        reason: RevocationReason,
        comment: Option<&str>,
        revoked_by: &str,
        trust_domain: &str,
    ) -> Result<RevokedSVID, RevokeSVIDError>;
}

/// Errors that can occur during SVID revocation.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum RevokeSVIDError {
    /// The certificate with the given serial number was not found.
    CertificateNotFound(String),
    /// The certificate has already been revoked.
    AlreadyRevoked(String),
    /// A CA rotation is in progress, preventing revocation.
    CARotationInProgress,
    /// The store is unavailable.
    StoreUnavailable(String),
    /// An internal error occurred.
    Internal(String),
}

impl std::fmt::Display for RevokeSVIDError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::CertificateNotFound(serial) => {
                write!(f, "certificate not found: {}", serial)
            }
            Self::AlreadyRevoked(serial) => {
                write!(f, "certificate already revoked: {}", serial)
            }
            Self::CARotationInProgress => {
                write!(f, "CA rotation in progress, cannot revoke")
            }
            Self::StoreUnavailable(detail) => {
                write!(f, "store unavailable: {}", detail)
            }
            Self::Internal(detail) => {
                write!(f, "internal error: {}", detail)
            }
        }
    }
}

impl std::error::Error for RevokeSVIDError {}

/// The rotate certificate use case trait.
///
/// Handles certificate rotation for workloads that need to replace
/// their current SVID before it expires. The rotation is atomic:
/// the old certificate is added to the revocation list before
/// the new certificate is issued.
pub trait RotateCertificateUseCase: Send + Sync {
    /// Rotate a certificate.
    ///
    /// # Arguments
    /// * `current_serial` - The serial number of the current SVID
    /// * `spiffe_id` - The SPIFFE ID for the new SVID
    /// * `reason` - The reason for rotation
    /// * `trust_domain` - The trust domain
    ///
    /// # Errors
    /// Returns an error if the current certificate is not found,
    /// rotation is not required, or a concurrent rotation is in progress.
    fn rotate_certificate(
        &self,
        current_serial: &str,
        spiffe_id: &str,
        reason: RotationReason,
        trust_domain: &str,
    ) -> Result<RotationResult, RotationError>;
}

/// Errors that can occur during certificate rotation.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum RotationError {
    /// The current certificate was not found.
    CertificateNotFound(String),
    /// Rotation is not required (SVID is still valid with ample TTL).
    RotationNotRequired,
    /// A CA rotation is in progress.
    CARotationInProgress,
    /// A concurrent rotation is already in progress for this workload.
    ConcurrentRotation(String),
    /// The signing key is unavailable.
    SigningKeyUnavailable(String),
    /// An internal error occurred.
    Internal(String),
}

impl std::fmt::Display for RotationError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::CertificateNotFound(serial) => {
                write!(f, "certificate not found: {}", serial)
            }
            Self::RotationNotRequired => {
                write!(f, "rotation not required, SVID has ample TTL")
            }
            Self::CARotationInProgress => {
                write!(f, "CA rotation in progress")
            }
            Self::ConcurrentRotation(spiffe_id) => {
                write!(f, "concurrent rotation in progress for: {}", spiffe_id)
            }
            Self::SigningKeyUnavailable(detail) => {
                write!(f, "signing key unavailable: {}", detail)
            }
            Self::Internal(detail) => {
                write!(f, "internal error: {}", detail)
            }
        }
    }
}

impl std::error::Error for RotationError {}

/// The get trust bundle use case trait.
///
/// Retrieves the current X.509 trust bundle for a trust domain.
/// The bundle includes all active root CA certificates and their
/// intermediate chains, along with a sequence number for
/// change detection.
pub trait GetTrustBundleUseCase: Send + Sync {
    /// Get the trust bundle for a trust domain.
    ///
    /// # Arguments
    /// * `trust_domain` - The trust domain to get the bundle for
    /// * `include_revoked` - Whether to include revoked certificates
    ///   (for administrative debugging)
    fn get_trust_bundle(
        &self,
        trust_domain: &str,
        include_revoked: bool,
    ) -> Result<X509Bundle, TrustBundleError>;
}

/// Errors that can occur when retrieving a trust bundle.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum TrustBundleError {
    /// The specified trust domain is not recognized.
    TrustDomainNotFound(String),
    /// The bundle is not yet ready (e.g., during CA rotation).
    BundleNotReady(String),
    /// An internal error occurred.
    Internal(String),
}

impl std::fmt::Display for TrustBundleError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::TrustDomainNotFound(domain) => {
                write!(f, "trust domain not found: {}", domain)
            }
            Self::BundleNotReady(domain) => {
                write!(f, "trust bundle not ready for: {}", domain)
            }
            Self::Internal(detail) => {
                write!(f, "internal error: {}", detail)
            }
        }
    }
}

impl std::error::Error for TrustBundleError {}
