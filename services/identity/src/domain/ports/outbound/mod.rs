// ---------------------------------------------------------------------------
// Outbound Ports Module
// ---------------------------------------------------------------------------
// Outbound ports are traits that the domain layer uses to interact
// with external systems. Adapters provide implementations.
// ---------------------------------------------------------------------------

pub mod ca;
pub mod store;

pub use ca::{CAError, CertificateAuthorityPort, GeneratedSVID, SignedSVID};
pub use store::{StoreError, StoredSVID, WorkloadList, WorkloadStorePort};
