// ---------------------------------------------------------------------------
// Outbound Port: Certificate Authority
// ---------------------------------------------------------------------------
// Defines the trait for certificate signing and CA operations.
// The domain service uses this port to sign SVIDs without knowing
// the implementation details (ring, OpenSSL, HSM, etc.).
// ZERO external dependencies — only std and domain models.
// ---------------------------------------------------------------------------

use crate::domain::models::X509Bundle;

/// The certificate authority outbound port.
///
/// This port abstracts the CA signing operations. The domain layer
/// calls this port to sign CSRs and manage the CA lifecycle. The
/// actual implementation uses ring for memory-safe, zero-cost
/// cryptographic operations.
pub trait CertificateAuthorityPort: Send + Sync {
    /// Sign a CSR (Certificate Signing Request) and return the
    /// DER-encoded certificate chain.
    ///
    /// # Arguments
    /// * `csr_der` - DER-encoded CSR
    /// * `spiffe_id` - SPIFFE ID to embed in the URI SAN
    /// * `dns_names` - DNS names to include in the SAN
    /// * `ttl_seconds` - TTL for the issued certificate
    ///
    /// # Returns
    /// A tuple of (DER-encoded cert chain, PEM-encoded cert chain,
    /// serial number, not_before timestamp, not_after timestamp).
    fn sign_svid(
        &self,
        csr_der: &[u8],
        spiffe_id: &str,
        dns_names: &[String],
        ttl_seconds: u64,
    ) -> Result<SignedSVID, CAError>;

    /// Generate a new key pair and CSR, then sign the SVID.
    ///
    /// This is used when the caller does not provide a CSR and wants
    /// the CA to generate the key pair. The private key is returned
    /// in encrypted PKCS#8 format.
    ///
    /// # Arguments
    /// * `spiffe_id` - SPIFFE ID to embed in the URI SAN
    /// * `dns_names` - DNS names to include in the SAN
    /// * `ttl_seconds` - TTL for the issued certificate
    fn generate_and_sign_svid(
        &self,
        spiffe_id: &str,
        dns_names: &[String],
        ttl_seconds: u64,
    ) -> Result<GeneratedSVID, CAError>;

    /// Get the current trust bundle (root CA certificates).
    fn get_trust_bundle(&self, trust_domain: &str) -> Result<X509Bundle, CAError>;

    /// Rotate the CA key. This is an administrative operation that
    /// generates a new CA key pair and re-issues the CA certificate.
    /// Existing SVIDs remain valid until they expire.
    fn rotate_ca_key(&self, trust_domain: &str) -> Result<(), CAError>;

    /// Check if a CA rotation is in progress.
    fn is_ca_rotation_in_progress(&self) -> bool;
}

/// A signed SVID returned by the CA.
#[derive(Debug, Clone)]
pub struct SignedSVID {
    /// DER-encoded certificate chain (leaf + intermediates + root).
    pub cert_chain_der: Vec<Vec<u8>>,
    /// PEM-encoded certificate chain.
    pub cert_chain_pem: String,
    /// The serial number of the leaf certificate.
    pub serial_number: String,
    /// The timestamp (Unix epoch seconds) when the certificate becomes valid.
    pub not_before: u64,
    /// The timestamp (Unix epoch seconds) when the certificate expires.
    pub not_after: u64,
}

/// A generated and signed SVID, including the private key.
#[derive(Debug, Clone)]
pub struct GeneratedSVID {
    /// The signed SVID.
    pub svid: SignedSVID,
    /// The DER-encoded private key (PKCS#8, encrypted).
    pub private_key_der: Vec<u8>,
    /// The PEM-encoded private key (PKCS#8, encrypted).
    pub private_key_pem: String,
}

/// Errors that can occur during CA operations.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum CAError {
    /// The CSR is malformed or invalid.
    InvalidCSR(String),
    /// The requested TTL is invalid.
    InvalidTTL(String),
    /// The SPIFFE ID is invalid for a certificate.
    InvalidSPIFFEID(String),
    /// The signing key is unavailable (e.g., HSM error).
    SigningKeyUnavailable(String),
    /// A CA rotation is in progress.
    RotationInProgress,
    /// The trust domain is not recognized.
    TrustDomainNotFound(String),
    /// An internal cryptographic error occurred.
    CryptoError(String),
}

impl std::fmt::Display for CAError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::InvalidCSR(detail) => write!(f, "invalid CSR: {}", detail),
            Self::InvalidTTL(detail) => write!(f, "invalid TTL: {}", detail),
            Self::InvalidSPIFFEID(detail) => write!(f, "invalid SPIFFE ID: {}", detail),
            Self::SigningKeyUnavailable(detail) => {
                write!(f, "signing key unavailable: {}", detail)
            }
            Self::RotationInProgress => write!(f, "CA rotation in progress"),
            Self::TrustDomainNotFound(domain) => write!(f, "trust domain not found: {}", domain),
            Self::CryptoError(detail) => write!(f, "crypto error: {}", detail),
        }
    }
}

impl std::error::Error for CAError {}
