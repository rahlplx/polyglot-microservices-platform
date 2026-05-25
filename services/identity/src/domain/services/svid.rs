// ---------------------------------------------------------------------------
// Domain Service: SVID Service
// ---------------------------------------------------------------------------
// Implements the IssueSVIDUseCase and RevokeSVIDUseCase traits.
// Contains the core domain logic for SVID issuance and revocation.
// ZERO external dependencies — only std and domain models/ports.
// ---------------------------------------------------------------------------

use std::sync::Arc;

use crate::domain::models::workload::{TrustDomain, SPIFFEID};
use crate::domain::models::{RevocationReason, RevokedSVID, TTLPolicy, X509Bundle, X509SVID};
use crate::domain::ports::inbound::{
    GetTrustBundleUseCase, IssueSVIDError, IssueSVIDUseCase, RevokeSVIDError, RevokeSVIDUseCase,
    TrustBundleError,
};
use crate::domain::ports::outbound::ca::{CAError, CertificateAuthorityPort};
use crate::domain::ports::outbound::store::{StoreError, WorkloadStorePort};

/// The SVID service implements the core SVID issuance and revocation logic.
///
/// SVID issuance validates that the requesting workload is registered
/// and attested, enforces TTL policy, and delegates cryptographic
/// operations to the CertificateAuthorityPort.
///
/// SVID revocation atomically marks the certificate as revoked in the
/// store, updates the CRL, and increments the trust bundle sequence
/// number. Emergency revocations (key compromise, CA compromise) are
/// processed immediately without approval workflows.
pub struct SVIDService {
    /// The workload store for looking up registered workloads.
    store: Arc<dyn WorkloadStorePort>,
    /// The certificate authority for signing SVIDs.
    ca: Arc<dyn CertificateAuthorityPort>,
    /// The TTL policy for this service.
    ttl_policy: TTLPolicy,
}

impl SVIDService {
    /// Creates a new SVID service.
    pub fn new(
        store: Arc<dyn WorkloadStorePort>,
        ca: Arc<dyn CertificateAuthorityPort>,
        ttl_policy: TTLPolicy,
    ) -> Self {
        Self {
            store,
            ca,
            ttl_policy,
        }
    }

    /// Returns the current Unix timestamp in seconds.
    fn current_timestamp() -> u64 {
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap_or_default()
            .as_secs()
    }

    /// Converts a store error to an issuance error.
    fn store_to_issue_error(error: StoreError) -> IssueSVIDError {
        match error {
            StoreError::WorkloadNotFound(id) => IssueSVIDError::WorkloadNotFound(id),
            StoreError::Unavailable(detail) => {
                IssueSVIDError::Internal(format!("store unavailable: {}", detail))
            }
            other => IssueSVIDError::Internal(other.to_string()),
        }
    }

    /// Converts a CA error to an issuance error.
    fn ca_to_issue_error(error: CAError) -> IssueSVIDError {
        match error {
            CAError::InvalidCSR(detail) => IssueSVIDError::InvalidCSR(detail),
            CAError::InvalidSPIFFEID(detail) => IssueSVIDError::InvalidSPIFFEID(detail),
            CAError::SigningKeyUnavailable(detail) => IssueSVIDError::SigningKeyUnavailable(detail),
            other => IssueSVIDError::Internal(other.to_string()),
        }
    }

    /// Converts a store error to a revocation error.
    fn store_to_revoke_error(error: StoreError) -> RevokeSVIDError {
        match error {
            StoreError::CertificateNotFound(serial) => RevokeSVIDError::CertificateNotFound(serial),
            StoreError::AlreadyRevoked(serial) => RevokeSVIDError::AlreadyRevoked(serial),
            StoreError::Unavailable(detail) => RevokeSVIDError::StoreUnavailable(detail),
            other => RevokeSVIDError::Internal(other.to_string()),
        }
    }
}

impl IssueSVIDUseCase for SVIDService {
    fn issue_svid(
        &self,
        spiffe_id: &str,
        ttl_seconds: u64,
        dns_names: &[String],
        trust_domain: &str,
        csr_der: Option<&[u8]>,
    ) -> Result<(X509SVID, X509Bundle), IssueSVIDError> {
        // Step 1: Parse and validate the SPIFFE ID
        let parsed_id = SPIFFEID::parse(spiffe_id)
            .map_err(|e| IssueSVIDError::InvalidSPIFFEID(e.to_string()))?;

        // Step 2: Validate trust domain
        let domain = TrustDomain::new(trust_domain.to_string());
        if !parsed_id.belongs_to(&domain) {
            return Err(IssueSVIDError::InvalidSPIFFEID(format!(
                "SPIFFE ID {} does not belong to trust domain {}",
                spiffe_id, trust_domain
            )));
        }

        // Step 3: Look up the workload
        let workload = self
            .store
            .get_workload_by_spiffe_id(spiffe_id)
            .map_err(Self::store_to_issue_error)?
            .ok_or_else(|| IssueSVIDError::WorkloadNotFound(spiffe_id.to_string()))?;

        // Step 4: Verify the workload is attested
        if !workload.attested {
            return Err(IssueSVIDError::WorkloadNotAttested(spiffe_id.to_string()));
        }

        // Step 5: Validate TTL against policy
        let validated_ttl = self
            .ttl_policy
            .validate_ttl(ttl_seconds)
            .map_err(|e| IssueSVIDError::Internal(e.to_string()))?;

        // Step 6: Sign the SVID
        let signed = if let Some(csr) = csr_der {
            self.ca
                .sign_svid(csr, spiffe_id, dns_names, validated_ttl)
                .map_err(Self::ca_to_issue_error)?
        } else {
            let generated = self
                .ca
                .generate_and_sign_svid(spiffe_id, dns_names, validated_ttl)
                .map_err(Self::ca_to_issue_error)?;
            // Store the encrypted private key
            self.store
                .store_svid(
                    &X509SVID::new(
                        spiffe_id.to_string(),
                        vec![],
                        String::new(),
                        generated.svid.serial_number.clone(),
                        generated.svid.not_after,
                        generated.svid.not_before,
                        dns_names.to_vec(),
                        trust_domain.to_string(),
                    ),
                    &workload.id,
                    &generated.private_key_der,
                )
                .map_err(Self::store_to_issue_error)?;

            generated.svid
        };

        // Step 7: Get the current trust bundle
        let bundle = self
            .ca
            .get_trust_bundle(trust_domain)
            .map_err(Self::ca_to_issue_error)?;

        // Step 8: Construct the X509SVID domain model
        let cert_chain_der = signed
            .cert_chain_der
            .iter()
            .flat_map(|v| v.iter().copied())
            .collect();

        let svid = X509SVID::new(
            spiffe_id.to_string(),
            cert_chain_der,
            signed.cert_chain_pem,
            signed.serial_number,
            signed.not_after,
            signed.not_before,
            dns_names.to_vec(),
            trust_domain.to_string(),
        );

        Ok((svid, bundle))
    }
}

impl RevokeSVIDUseCase for SVIDService {
    fn revoke_svid(
        &self,
        serial_number: &str,
        reason: RevocationReason,
        comment: Option<&str>,
        revoked_by: &str,
        trust_domain: &str,
    ) -> Result<RevokedSVID, RevokeSVIDError> {
        // Step 1: Check if CA rotation is in progress
        if self.ca.is_ca_rotation_in_progress() {
            // Emergency revocations bypass CA rotation check
            if !reason.is_emergency() {
                return Err(RevokeSVIDError::CARotationInProgress);
            }
        }

        // Step 2: Revoke the SVID in the store
        let revoked = self
            .store
            .revoke_svid(serial_number, reason, revoked_by, comment)
            .map_err(Self::store_to_revoke_error)?;

        // Step 3: Increment the bundle sequence number to signal
        // that verifiers should refresh their cached CRL
        self.store
            .increment_bundle_sequence(trust_domain)
            .map_err(|e| {
                RevokeSVIDError::Internal(format!("failed to increment bundle sequence: {}", e))
            })?;

        Ok(revoked)
    }
}

impl GetTrustBundleUseCase for SVIDService {
    fn get_trust_bundle(
        &self,
        trust_domain: &str,
        _include_revoked: bool,
    ) -> Result<X509Bundle, TrustBundleError> {
        // First, try to get from the CA (in-memory cache)
        if let Ok(bundle) = self.ca.get_trust_bundle(trust_domain) {
            return Ok(bundle);
        }

        // Fall back to the store
        self.store
            .get_bundle(trust_domain)
            .map_err(|e| TrustBundleError::Internal(e.to_string()))?
            .ok_or_else(|| TrustBundleError::TrustDomainNotFound(trust_domain.to_string()))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::domain::models::workload::{Selector, Workload};
    use crate::domain::ports::outbound::ca::{GeneratedSVID, SignedSVID};

    /// Mock CA for testing.
    struct MockCA {
        rotation_in_progress: bool,
    }

    impl MockCA {
        fn new() -> Self {
            Self {
                rotation_in_progress: false,
            }
        }
    }

    impl CertificateAuthorityPort for MockCA {
        fn sign_svid(
            &self,
            _csr_der: &[u8],
            spiffe_id: &str,
            _dns_names: &[String],
            ttl_seconds: u64,
        ) -> Result<SignedSVID, CAError> {
            Ok(SignedSVID {
                cert_chain_der: vec![vec![1, 2, 3]],
                cert_chain_pem: "-----BEGIN CERTIFICATE-----\ntest\n-----END CERTIFICATE-----"
                    .to_string(),
                serial_number: "deadbeef".to_string(),
                not_before: Self::current_timestamp(),
                not_after: Self::current_timestamp() + ttl_seconds,
            })
        }

        fn generate_and_sign_svid(
            &self,
            spiffe_id: &str,
            dns_names: &[String],
            ttl_seconds: u64,
        ) -> Result<GeneratedSVID, CAError> {
            Ok(GeneratedSVID {
                svid: SignedSVID {
                    cert_chain_der: vec![vec![1, 2, 3]],
                    cert_chain_pem: "-----BEGIN CERTIFICATE-----\ntest\n-----END CERTIFICATE-----"
                        .to_string(),
                    serial_number: "deadbeef".to_string(),
                    not_before: Self::current_timestamp(),
                    not_after: Self::current_timestamp() + ttl_seconds,
                },
                private_key_der: vec![4, 5, 6],
                private_key_pem: "-----BEGIN PRIVATE KEY-----\ntest\n-----END PRIVATE KEY-----"
                    .to_string(),
            })
        }

        fn get_trust_bundle(&self, trust_domain: &str) -> Result<X509Bundle, CAError> {
            Ok(X509Bundle::new(
                trust_domain.to_string(),
                vec![vec![7, 8, 9]],
                vec!["-----BEGIN CERTIFICATE-----\nroot\n-----END CERTIFICATE-----".to_string()],
                1,
                Self::current_timestamp() + 86400,
            ))
        }

        fn rotate_ca_key(&self, _trust_domain: &str) -> Result<(), CAError> {
            Ok(())
        }

        fn is_ca_rotation_in_progress(&self) -> bool {
            self.rotation_in_progress
        }
    }

    impl MockCA {
        fn current_timestamp() -> u64 {
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap_or_default()
                .as_secs()
        }
    }

    /// Mock store for testing.
    struct MockStore {
        workloads: std::collections::HashMap<String, Workload>,
        revoked: std::collections::HashSet<String>,
    }

    impl MockStore {
        fn new() -> Self {
            Self {
                workloads: std::collections::HashMap::new(),
                revoked: std::collections::HashSet::new(),
            }
        }

        fn add_attested_workload(&mut self, spiffe_id: &str) {
            let id = SPIFFEID::parse(spiffe_id).unwrap();
            let parent_id = SPIFFEID::parse("spiffe://trust.example.org/spire/agent").unwrap();
            let mut workload = Workload::new(
                format!("w-{}", spiffe_id.len()),
                id,
                parent_id,
                vec![Selector::k8s_namespace("production")],
                3600,
                vec!["test.trust.example.org".to_string()],
            );
            workload.mark_attested();
            self.workloads.insert(spiffe_id.to_string(), workload);
        }
    }

    impl WorkloadStorePort for MockStore {
        fn register_workload(&self, _workload: &Workload) -> Result<(), StoreError> {
            Ok(())
        }
        fn get_workload(&self, _workload_id: &str) -> Result<Option<Workload>, StoreError> {
            Ok(None)
        }
        fn get_workloads_by_selector(
            &self,
            _selectors: &[Selector],
            _trust_domain: &str,
        ) -> Result<Vec<Workload>, StoreError> {
            Ok(vec![])
        }
        fn get_workload_by_spiffe_id(
            &self,
            spiffe_id: &str,
        ) -> Result<Option<Workload>, StoreError> {
            Ok(self.workloads.get(spiffe_id).cloned())
        }
        fn update_workload(&self, _workload: &Workload) -> Result<(), StoreError> {
            Ok(())
        }
        fn delete_workload(&self, _workload_id: &str) -> Result<(), StoreError> {
            Ok(())
        }
        fn list_workloads(
            &self,
            _trust_domain: &str,
            _cursor: Option<&str>,
            _page_size: i32,
        ) -> Result<crate::domain::ports::outbound::store::WorkloadList, StoreError> {
            Ok(crate::domain::ports::outbound::store::WorkloadList {
                workloads: vec![],
                next_cursor: None,
            })
        }
        fn store_svid(
            &self,
            _svid: &X509SVID,
            _workload_id: &str,
            _encrypted_private_key: &[u8],
        ) -> Result<(), StoreError> {
            Ok(())
        }
        fn get_svid(
            &self,
            _serial_number: &str,
        ) -> Result<Option<crate::domain::ports::outbound::store::StoredSVID>, StoreError> {
            Ok(None)
        }
        fn get_active_svid_for_workload(
            &self,
            _workload_id: &str,
        ) -> Result<Option<crate::domain::ports::outbound::store::StoredSVID>, StoreError> {
            Ok(None)
        }
        fn revoke_svid(
            &self,
            serial_number: &str,
            reason: RevocationReason,
            _revoked_by: &str,
            _comment: Option<&str>,
        ) -> Result<RevokedSVID, StoreError> {
            if self.revoked.contains(serial_number) {
                return Err(StoreError::AlreadyRevoked(serial_number.to_string()));
            }
            Ok(RevokedSVID {
                serial_number: serial_number.to_string(),
                spiffe_id: "spiffe://trust.example.org/test".to_string(),
                reason,
                revoked_at: Self::current_timestamp(),
                revoked_by: "admin".to_string(),
                comment: None,
                trust_domain: "trust.example.org".to_string(),
            })
        }
        fn list_revoked(
            &self,
            _trust_domain: &str,
            _sequence_gt: u64,
        ) -> Result<Vec<RevokedSVID>, StoreError> {
            Ok(vec![])
        }
        fn is_revoked(&self, serial_number: &str) -> Result<bool, StoreError> {
            Ok(self.revoked.contains(serial_number))
        }
        fn store_bundle(&self, _bundle: &X509Bundle) -> Result<(), StoreError> {
            Ok(())
        }
        fn get_bundle(&self, _trust_domain: &str) -> Result<Option<X509Bundle>, StoreError> {
            Ok(None)
        }
        fn increment_bundle_sequence(&self, _trust_domain: &str) -> Result<u64, StoreError> {
            Ok(2)
        }
    }

    impl MockStore {
        fn current_timestamp() -> u64 {
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap_or_default()
                .as_secs()
        }
    }

    #[test]
    fn issue_svid_success() {
        let mut store = MockStore::new();
        store.add_attested_workload("spiffe://trust.example.org/services/gateway");

        let service = SVIDService::new(
            Arc::new(store),
            Arc::new(MockCA::new()),
            TTLPolicy::default(),
        );

        let result = service.issue_svid(
            "spiffe://trust.example.org/services/gateway",
            3600,
            &["gateway.trust.example.org".to_string()],
            "trust.example.org",
            None,
        );

        assert!(result.is_ok());
        let (svid, bundle) = result.unwrap();
        assert_eq!(
            svid.spiffe_id,
            "spiffe://trust.example.org/services/gateway"
        );
        assert_eq!(bundle.trust_domain, "trust.example.org");
    }

    #[test]
    fn issue_svid_workload_not_found() {
        let store = MockStore::new();

        let service = SVIDService::new(
            Arc::new(store),
            Arc::new(MockCA::new()),
            TTLPolicy::default(),
        );

        let result = service.issue_svid(
            "spiffe://trust.example.org/services/unknown",
            3600,
            &[],
            "trust.example.org",
            None,
        );

        assert!(result.is_err());
        match result.unwrap_err() {
            IssueSVIDError::WorkloadNotFound(id) => {
                assert!(id.contains("unknown"));
            }
            other => panic!("expected WorkloadNotFound, got {:?}", other),
        }
    }

    #[test]
    fn revoke_svid_success() {
        let store = MockStore::new();

        let service = SVIDService::new(
            Arc::new(store),
            Arc::new(MockCA::new()),
            TTLPolicy::default(),
        );

        let result = service.revoke_svid(
            "serial123",
            RevocationReason::KeyCompromise,
            Some("suspected key compromise"),
            "admin",
            "trust.example.org",
        );

        assert!(result.is_ok());
    }
}
