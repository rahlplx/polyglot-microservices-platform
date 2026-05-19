// ---------------------------------------------------------------------------
// Outbound Port: Workload Store
// ---------------------------------------------------------------------------
// Defines the trait for workload registration and certificate storage.
// The domain service uses this port to persist and retrieve workload
// and certificate data. ZERO external dependencies.
// ---------------------------------------------------------------------------

use crate::domain::models::{
    RevocationReason, RevokedSVID, X509Bundle, X509SVID,
};
use crate::domain::models::workload::{Selector, Workload};

/// The workload store outbound port.
///
/// This port abstracts all persistent storage operations for workloads,
/// certificates, and trust bundles. The domain layer calls this port
/// to register workloads, store issued SVIDs, and manage revocations.
/// The actual implementation uses PostgreSQL with sqlx for async,
/// compile-time checked queries.
pub trait WorkloadStorePort: Send + Sync {
    // --- Workload operations ---

    /// Register a new workload.
    fn register_workload(&self, workload: &Workload) -> Result<(), StoreError>;

    /// Get a workload by its ID.
    fn get_workload(&self, workload_id: &str) -> Result<Option<Workload>, StoreError>;

    /// Get workloads matching the given selectors.
    fn get_workloads_by_selector(
        &self,
        selectors: &[Selector],
        trust_domain: &str,
    ) -> Result<Vec<Workload>, StoreError>;

    /// Get a workload by its SPIFFE ID.
    fn get_workload_by_spiffe_id(
        &self,
        spiffe_id: &str,
    ) -> Result<Option<Workload>, StoreError>;

    /// Update a workload's registration.
    fn update_workload(&self, workload: &Workload) -> Result<(), StoreError>;

    /// Delete a workload registration.
    fn delete_workload(&self, workload_id: &str) -> Result<(), StoreError>;

    /// List workloads in a trust domain with cursor-based pagination.
    fn list_workloads(
        &self,
        trust_domain: &str,
        cursor: Option<&str>,
        page_size: i32,
    ) -> Result<WorkloadList, StoreError>;

    // --- SVID/Certificate operations ---

    /// Store an issued SVID.
    fn store_svid(
        &self,
        svid: &X509SVID,
        workload_id: &str,
        encrypted_private_key: &[u8],
    ) -> Result<(), StoreError>;

    /// Get an SVID by serial number.
    fn get_svid(&self, serial_number: &str) -> Result<Option<StoredSVID>, StoreError>;

    /// Get the active SVID for a workload.
    fn get_active_svid_for_workload(
        &self,
        workload_id: &str,
    ) -> Result<Option<StoredSVID>, StoreError>;

    /// Revoke an SVID by serial number.
    fn revoke_svid(
        &self,
        serial_number: &str,
        reason: RevocationReason,
        revoked_by: &str,
        comment: Option<&str>,
    ) -> Result<RevokedSVID, StoreError>;

    /// List revoked SVIDs with sequence number greater than the given value.
    /// Used for CRL distribution and incremental bundle updates.
    fn list_revoked(
        &self,
        trust_domain: &str,
        sequence_gt: u64,
    ) -> Result<Vec<RevokedSVID>, StoreError>;

    /// Check if a serial number has been revoked.
    fn is_revoked(&self, serial_number: &str) -> Result<bool, StoreError>;

    // --- Trust bundle operations ---

    /// Store the trust bundle for a trust domain.
    fn store_bundle(&self, bundle: &X509Bundle) -> Result<(), StoreError>;

    /// Get the trust bundle for a trust domain.
    fn get_bundle(&self, trust_domain: &str) -> Result<Option<X509Bundle>, StoreError>;

    /// Increment the bundle sequence number (used on revocation or CA rotation).
    fn increment_bundle_sequence(&self, trust_domain: &str) -> Result<u64, StoreError>;
}

/// A stored SVID record (includes metadata not in the domain model).
#[derive(Debug, Clone)]
pub struct StoredSVID {
    /// The SVID.
    pub svid: X509SVID,
    /// The workload ID this SVID was issued to.
    pub workload_id: String,
    /// Whether this SVID has been revoked.
    pub is_revoked: bool,
    /// The encrypted private key (PKCS#8, AES-256-GCM encrypted).
    pub encrypted_private_key: Vec<u8>,
}

/// A paginated list of workloads.
#[derive(Debug, Clone)]
pub struct WorkloadList {
    /// The workloads in this page.
    pub workloads: Vec<Workload>,
    /// The cursor for the next page, if more results exist.
    pub next_cursor: Option<String>,
}

/// Errors that can occur during store operations.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum StoreError {
    /// A workload with the given ID already exists.
    DuplicateWorkload(String),
    /// A certificate with the given serial already exists.
    DuplicateCertificate(String),
    /// The workload was not found.
    WorkloadNotFound(String),
    /// The certificate was not found.
    CertificateNotFound(String),
    /// The trust domain was not found.
    TrustDomainNotFound(String),
    /// The certificate has already been revoked.
    AlreadyRevoked(String),
    /// A serialization/deserialization error occurred.
    SerializationError(String),
    /// The database is unavailable.
    Unavailable(String),
    /// A transaction conflict occurred (serializable isolation).
    Conflict(String),
    /// An internal database error occurred.
    Internal(String),
}

impl std::fmt::Display for StoreError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::DuplicateWorkload(id) => write!(f, "duplicate workload: {}", id),
            Self::DuplicateCertificate(serial) => {
                write!(f, "duplicate certificate: {}", serial)
            }
            Self::WorkloadNotFound(id) => write!(f, "workload not found: {}", id),
            Self::CertificateNotFound(serial) => {
                write!(f, "certificate not found: {}", serial)
            }
            Self::TrustDomainNotFound(domain) => {
                write!(f, "trust domain not found: {}", domain)
            }
            Self::AlreadyRevoked(serial) => {
                write!(f, "certificate already revoked: {}", serial)
            }
            Self::SerializationError(detail) => {
                write!(f, "serialization error: {}", detail)
            }
            Self::Unavailable(detail) => write!(f, "store unavailable: {}", detail),
            Self::Conflict(detail) => write!(f, "conflict: {}", detail),
            Self::Internal(detail) => write!(f, "internal error: {}", detail),
        }
    }
}

impl std::error::Error for StoreError {}
