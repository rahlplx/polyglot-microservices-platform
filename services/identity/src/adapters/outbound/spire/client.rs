// ---------------------------------------------------------------------------
// SPIRE Agent Client Adapter
// ---------------------------------------------------------------------------
// Implements the outbound port for communicating with the SPIRE Agent.
// This adapter handles the SPIRE Workload API interactions for workload
// attestation and SVID retrieval.
// ---------------------------------------------------------------------------

use crate::domain::models::X509Bundle;
use crate::domain::ports::outbound::ca::{
    CAError, CertificateAuthorityPort, GeneratedSVID, SignedSVID,
};

/// The SPIRE Agent client adapter.
///
/// This adapter communicates with the SPIRE Agent via its Workload API
/// endpoint (typically a Unix domain socket at
/// `/run/spire/sockets/agent.sock`). It delegates certificate signing
/// operations to the SPIRE Agent, which manages the CA key material
/// and signing operations.
///
/// In this implementation, the SPIRE Agent acts as a signing oracle:
/// the Identity service generates key pairs and CSRs locally, then
/// sends the CSR to the SPIRE Agent for signing. This ensures that
/// the CA private key never leaves the SPIRE Agent's secure enclave.
pub struct SPIREAgentClient {
    /// The SPIRE Agent socket path.
    socket_path: String,
    /// The trust domain this agent belongs to.
    trust_domain: String,
    /// Whether a CA rotation is in progress.
    ca_rotation_in_progress: std::sync::atomic::AtomicBool,
}

impl SPIREAgentClient {
    /// Creates a new SPIRE Agent client.
    pub fn new(socket_path: String, trust_domain: String) -> Self {
        Self {
            socket_path,
            trust_domain,
            ca_rotation_in_progress: std::sync::atomic::AtomicBool::new(false),
        }
    }

    /// Returns the socket path for the SPIRE Agent.
    pub fn socket_path(&self) -> &str {
        &self.socket_path
    }

    /// Returns the trust domain for this SPIRE Agent.
    pub fn trust_domain(&self) -> &str {
        &self.trust_domain
    }
}

impl CertificateAuthorityPort for SPIREAgentClient {
    fn sign_svid(
        &self,
        csr_der: &[u8],
        spiffe_id: &str,
        dns_names: &[String],
        ttl_seconds: u64,
    ) -> Result<SignedSVID, CAError> {
        // In production, this would make a gRPC call to the SPIRE Agent's
        // Workload API to sign the CSR. For now, we return an error
        // indicating that the SPIRE Agent connection is not available.
        //
        // The actual implementation would:
        // 1. Connect to the SPIRE Agent via Unix domain socket
        // 2. Call the SignX509SVID RPC with the CSR
        // 3. Return the signed certificate chain
        Err(CAError::SigningKeyUnavailable(
            "SPIRE Agent connection not yet implemented".to_string(),
        ))
    }

    fn generate_and_sign_svid(
        &self,
        spiffe_id: &str,
        dns_names: &[String],
        ttl_seconds: u64,
    ) -> Result<GeneratedSVID, CAError> {
        // In production, this would:
        // 1. Generate a key pair locally using ring
        // 2. Create a CSR with the SPIFFE ID in the URI SAN
        // 3. Send the CSR to the SPIRE Agent for signing
        // 4. Return the signed SVID with the encrypted private key
        Err(CAError::SigningKeyUnavailable(
            "SPIRE Agent connection not yet implemented".to_string(),
        ))
    }

    fn get_trust_bundle(&self, trust_domain: &str) -> Result<X509Bundle, CAError> {
        // In production, this would fetch the trust bundle from the
        // SPIRE Agent's Workload API.
        Err(CAError::TrustDomainNotFound(trust_domain.to_string()))
    }

    fn rotate_ca_key(&self, trust_domain: &str) -> Result<(), CAError> {
        self.ca_rotation_in_progress
            .store(true, std::sync::atomic::Ordering::SeqCst);

        // In production, this would trigger a CA rotation via the
        // SPIRE Server's admin API. The rotation process:
        // 1. Generate a new CA key pair
        // 2. Issue a new CA certificate
        // 3. Publish the new trust bundle
        // 4. Gradually rotate SVIDs under the new CA
        // 5. Mark rotation as complete

        self.ca_rotation_in_progress
            .store(false, std::sync::atomic::Ordering::SeqCst);

        Ok(())
    }

    fn is_ca_rotation_in_progress(&self) -> bool {
        self.ca_rotation_in_progress
            .load(std::sync::atomic::Ordering::SeqCst)
    }
}
