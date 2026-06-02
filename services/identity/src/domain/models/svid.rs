// ---------------------------------------------------------------------------
// Domain Models: SVID, X509SVID
// ---------------------------------------------------------------------------
// This module contains the SVID (SPIFFE Verifiable Identity Document)
// domain models. ZERO external dependencies — only std is used.
// ---------------------------------------------------------------------------

/// An X.509 SVID (SPIFFE Verifiable Identity Document).
///
/// An X.509 SVID is a standard X.509 certificate that encodes a SPIFFE ID
/// in the URI SAN (Subject Alternative Name) field. It is the primary
/// identity document used for workload authentication in the SPIFFE framework.
///
/// SVIDs are issued by the Identity service's in-memory CA and have a
/// limited TTL (1 hour in production) to limit the blast radius of
/// credential compromise. The private key is held by the workload (or
/// the SPIRE Agent on the workload's behalf) and is never transmitted
/// to the Identity service.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct X509SVID {
    /// The SPIFFE ID encoded in this SVID.
    pub spiffe_id: String,
    /// The DER-encoded certificate chain (leaf + intermediates).
    pub cert_chain_der: Vec<u8>,
    /// The PEM-encoded certificate chain.
    pub cert_chain_pem: String,
    /// The serial number of the leaf certificate (hex-encoded).
    pub serial_number: String,
    /// The timestamp (Unix epoch seconds) when this SVID expires.
    pub expires_at: u64,
    /// The timestamp (Unix epoch seconds) when this SVID was issued.
    pub not_before: u64,
    /// DNS names included in the SVID's SAN field.
    pub dns_names: Vec<String>,
    /// The trust domain this SVID belongs to.
    pub trust_domain: String,
}

impl X509SVID {
    /// Creates a new X.509 SVID.
    pub fn new(
        spiffe_id: String,
        cert_chain_der: Vec<u8>,
        cert_chain_pem: String,
        serial_number: String,
        expires_at: u64,
        not_before: u64,
        dns_names: Vec<String>,
        trust_domain: String,
    ) -> Self {
        Self {
            spiffe_id,
            cert_chain_der,
            cert_chain_pem,
            serial_number,
            expires_at,
            not_before,
            dns_names,
            trust_domain,
        }
    }

    /// Returns true if this SVID has expired at the given timestamp.
    pub fn is_expired_at(&self, now: u64) -> bool {
        now >= self.expires_at
    }

    /// Returns true if this SVID is within the grace period of expiry.
    ///
    /// The grace period is the window before expiry during which the
    /// workload should initiate certificate rotation. By default,
    /// the grace period is 5 minutes (300 seconds).
    pub fn is_within_grace_period(&self, now: u64, grace_period_seconds: u64) -> bool {
        now >= self.expires_at.saturating_sub(grace_period_seconds) && now < self.expires_at
    }

    /// Returns the remaining TTL in seconds at the given timestamp.
    pub fn remaining_ttl(&self, now: u64) -> u64 {
        self.expires_at.saturating_sub(now)
    }

    /// Returns true if this SVID needs rotation at the given timestamp.
    ///
    /// Rotation is needed when the SVID is within the grace period or
    /// has already expired.
    pub fn needs_rotation(&self, now: u64, grace_period_seconds: u64) -> bool {
        self.is_within_grace_period(now, grace_period_seconds) || self.is_expired_at(now)
    }
}

/// An X.509 trust bundle.
///
/// The trust bundle contains the root CA certificates and intermediate
/// chains for a trust domain. Workloads use the trust bundle to verify
/// peer SVIDs during mTLS handshake. The bundle is periodically refreshed
/// and includes a sequence number for change detection.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct X509Bundle {
    /// The trust domain this bundle belongs to.
    pub trust_domain: String,
    /// DER-encoded root CA certificates.
    pub root_certs_der: Vec<Vec<u8>>,
    /// PEM-encoded root CA certificates.
    pub root_certs_pem: Vec<String>,
    /// The sequence number for bundle rotation tracking.
    /// Incremented each time the bundle is updated (e.g., on CA rotation).
    pub sequence_number: u64,
    /// The timestamp (Unix epoch seconds) when this bundle expires.
    pub expires_at: u64,
}

impl X509Bundle {
    /// Creates a new X.509 trust bundle.
    pub fn new(
        trust_domain: String,
        root_certs_der: Vec<Vec<u8>>,
        root_certs_pem: Vec<String>,
        sequence_number: u64,
        expires_at: u64,
    ) -> Self {
        Self {
            trust_domain,
            root_certs_der,
            root_certs_pem,
            sequence_number,
            expires_at,
        }
    }

    /// Returns true if this bundle has expired at the given timestamp.
    pub fn is_expired_at(&self, now: u64) -> bool {
        now >= self.expires_at
    }
}

/// The revocation status of an SVID.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RevocationStatus {
    /// The SVID is valid and not revoked.
    Active,
    /// The SVID has been revoked.
    Revoked(RevocationReason),
    /// The SVID has expired.
    Expired,
}

/// The reason an SVID was revoked.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RevocationReason {
    /// The private key is suspected to be compromised.
    KeyCompromise,
    /// The CA key is suspected to be compromised.
    CACompromise,
    /// The workload's affiliation has changed.
    AffiliationChanged,
    /// The SVID has been superseded by a new one.
    Superseded,
    /// The workload has ceased operation.
    CessationOfOperation,
    /// The certificate is temporarily on hold.
    CertificateHold,
    /// The certificate has been removed from the CRL.
    RemoveFromCRL,
    /// The workload's privileges have been withdrawn.
    PrivilegeWithdrawn,
    /// No specific reason given.
    Unspecified,
}

impl RevocationReason {
    /// Returns the numeric code for this revocation reason (RFC 5280).
    pub fn code(&self) -> u8 {
        match self {
            Self::KeyCompromise => 1,
            Self::CACompromise => 2,
            Self::AffiliationChanged => 3,
            Self::Superseded => 4,
            Self::CessationOfOperation => 5,
            Self::CertificateHold => 6,
            Self::RemoveFromCRL => 8,
            Self::PrivilegeWithdrawn => 9,
            Self::Unspecified => 0,
        }
    }

    /// Creates a RevocationReason from its numeric code.
    pub fn from_code(code: u8) -> Self {
        match code {
            1 => Self::KeyCompromise,
            2 => Self::CACompromise,
            3 => Self::AffiliationChanged,
            4 => Self::Superseded,
            5 => Self::CessationOfOperation,
            6 => Self::CertificateHold,
            8 => Self::RemoveFromCRL,
            9 => Self::PrivilegeWithdrawn,
            _ => Self::Unspecified,
        }
    }

    /// Returns true if this is an emergency revocation reason.
    ///
    /// Emergency revocations (key compromise, CA compromise) bypass
    /// normal approval workflows and are processed immediately.
    pub fn is_emergency(&self) -> bool {
        matches!(self, Self::KeyCompromise | Self::CACompromise)
    }
}

impl std::fmt::Display for RevocationReason {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::KeyCompromise => write!(f, "KEY_COMPROMISE"),
            Self::CACompromise => write!(f, "CA_COMPROMISE"),
            Self::AffiliationChanged => write!(f, "AFFILIATION_CHANGED"),
            Self::Superseded => write!(f, "SUPERSEDED"),
            Self::CessationOfOperation => write!(f, "CESSATION_OF_OPERATION"),
            Self::CertificateHold => write!(f, "CERTIFICATE_HOLD"),
            Self::RemoveFromCRL => write!(f, "REMOVE_FROM_CRL"),
            Self::PrivilegeWithdrawn => write!(f, "PRIVILEGE_WITHDRAWN"),
            Self::Unspecified => write!(f, "UNSPECIFIED"),
        }
    }
}

/// A record of a revoked SVID.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RevokedSVID {
    /// The serial number of the revoked certificate.
    pub serial_number: String,
    /// The SPIFFE ID of the revoked certificate.
    pub spiffe_id: String,
    /// The reason for revocation.
    pub reason: RevocationReason,
    /// The timestamp (Unix epoch seconds) when the SVID was revoked.
    pub revoked_at: u64,
    /// The identity that performed the revocation.
    pub revoked_by: String,
    /// Optional comment about the revocation.
    pub comment: Option<String>,
    /// The trust domain this SVID belongs to.
    pub trust_domain: String,
}

/// The reason for certificate rotation.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RotationReason {
    /// Proactive rotation before expiry (workload-initiated).
    Proactive,
    /// Expiry-driven rotation (automatic at rotation threshold).
    Expiry,
    /// CA rotation (existing SVIDs must be re-issued under new CA).
    CARotation,
    /// Key compromise (emergency rotation).
    KeyCompromise,
}

impl std::fmt::Display for RotationReason {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Proactive => write!(f, "PROACTIVE"),
            Self::Expiry => write!(f, "EXPIRY"),
            Self::CARotation => write!(f, "CA_ROTATION"),
            Self::KeyCompromise => write!(f, "KEY_COMPROMISE"),
        }
    }
}

/// The result of a certificate rotation operation.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RotationResult {
    /// The new SVID issued as part of the rotation.
    pub new_svid: X509SVID,
    /// The updated trust bundle.
    pub new_bundle: X509Bundle,
    /// Whether the old certificate was successfully revoked.
    pub old_serial_revoked: bool,
    /// A unique identifier for this rotation event (for audit tracking).
    pub rotation_id: String,
    /// The reason for the rotation.
    pub reason: RotationReason,
    /// The timestamp (Unix epoch seconds) when the rotation occurred.
    pub rotated_at: u64,
}

/// Certificate TTL policy configuration.
///
/// This struct encapsulates the policy for SVID TTL values across
/// different trust domains and environments.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TTLPolicy {
    /// Maximum allowed TTL in seconds (default: 72 hours = 259200).
    pub max_ttl_seconds: u64,
    /// Default TTL in seconds for production (1 hour = 3600).
    pub default_production_ttl_seconds: u64,
    /// Default TTL in seconds for staging (4 hours = 14400).
    pub default_staging_ttl_seconds: u64,
    /// Default TTL in seconds for development (24 hours = 86400).
    pub default_development_ttl_seconds: u64,
    /// Grace period before expiry for rotation (5 minutes = 300).
    pub grace_period_seconds: u64,
}

impl Default for TTLPolicy {
    fn default() -> Self {
        Self {
            max_ttl_seconds: 259200,                // 72 hours
            default_production_ttl_seconds: 3600,   // 1 hour
            default_staging_ttl_seconds: 14400,     // 4 hours
            default_development_ttl_seconds: 86400, // 24 hours
            grace_period_seconds: 300,              // 5 minutes
        }
    }
}

impl TTLPolicy {
    /// Returns the default TTL for the given trust domain.
    pub fn default_ttl_for_domain(&self, trust_domain: &str) -> u64 {
        if trust_domain == crate::domain::models::workload::TrustDomain::PRODUCTION {
            self.default_production_ttl_seconds
        } else if trust_domain == crate::domain::models::workload::TrustDomain::STAGING {
            self.default_staging_ttl_seconds
        } else {
            self.default_development_ttl_seconds
        }
    }

    /// Validates that the requested TTL is within policy limits.
    pub fn validate_ttl(&self, requested_ttl: u64) -> Result<u64, TTLPolicyError> {
        if requested_ttl == 0 {
            return Err(TTLPolicyError::ZeroTTL);
        }
        if requested_ttl > self.max_ttl_seconds {
            return Err(TTLPolicyError::TTLExceededPolicy {
                requested: requested_ttl,
                maximum: self.max_ttl_seconds,
            });
        }
        Ok(requested_ttl.min(self.max_ttl_seconds))
    }
}

/// Errors that can occur when validating TTL policy.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum TTLPolicyError {
    /// The requested TTL is zero.
    ZeroTTL,
    /// The requested TTL exceeds the maximum policy TTL.
    TTLExceededPolicy { requested: u64, maximum: u64 },
}

impl std::fmt::Display for TTLPolicyError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::ZeroTTL => write!(f, "requested TTL cannot be zero"),
            Self::TTLExceededPolicy { requested, maximum } => {
                write!(
                    f,
                    "requested TTL {}s exceeds maximum policy TTL {}s",
                    requested, maximum
                )
            }
        }
    }
}

impl std::error::Error for TTLPolicyError {}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn svid_expiry_check() {
        let svid = X509SVID::new(
            "spiffe://trust.example.org/services/gateway".to_string(),
            vec![],
            String::new(),
            "abc123".to_string(),
            1000,
            500,
            vec![],
            "trust.example.org".to_string(),
        );

        assert!(!svid.is_expired_at(999));
        assert!(svid.is_expired_at(1000));
        assert!(svid.is_expired_at(1001));
    }

    #[test]
    fn svid_grace_period() {
        let svid = X509SVID::new(
            "spiffe://trust.example.org/services/gateway".to_string(),
            vec![],
            String::new(),
            "abc123".to_string(),
            1000,
            500,
            vec![],
            "trust.example.org".to_string(),
        );

        // Grace period is 300 seconds, so grace starts at 700
        assert!(!svid.is_within_grace_period(699, 300));
        assert!(svid.is_within_grace_period(700, 300));
        assert!(svid.is_within_grace_period(999, 300));
        assert!(!svid.is_within_grace_period(1000, 300)); // Expired, not grace
    }

    #[test]
    fn svid_needs_rotation() {
        let svid = X509SVID::new(
            "spiffe://trust.example.org/services/gateway".to_string(),
            vec![],
            String::new(),
            "abc123".to_string(),
            1000,
            500,
            vec![],
            "trust.example.org".to_string(),
        );

        assert!(!svid.needs_rotation(699, 300));
        assert!(svid.needs_rotation(700, 300));
        assert!(svid.needs_rotation(1001, 300));
    }

    #[test]
    fn revocation_reason_codes() {
        assert_eq!(RevocationReason::KeyCompromise.code(), 1);
        assert_eq!(RevocationReason::CACompromise.code(), 2);
        assert_eq!(RevocationReason::Unspecified.code(), 0);
        assert_eq!(
            RevocationReason::from_code(1),
            RevocationReason::KeyCompromise
        );
    }

    #[test]
    fn emergency_revocation() {
        assert!(RevocationReason::KeyCompromise.is_emergency());
        assert!(RevocationReason::CACompromise.is_emergency());
        assert!(!RevocationReason::Superseded.is_emergency());
    }

    #[test]
    fn ttl_policy_validation() {
        let policy = TTLPolicy::default();

        assert!(policy.validate_ttl(3600).is_ok());
        assert!(policy.validate_ttl(0).is_err());
        assert!(policy.validate_ttl(300000).is_err());
    }
}
