// ---------------------------------------------------------------------------
// Domain Service: Attestation Service
// ---------------------------------------------------------------------------
// Implements the AttestationUseCase trait. Contains the core domain logic
// for workload attestation. ZERO external dependencies — only std and
// domain models/ports are used.
// ---------------------------------------------------------------------------

use std::sync::Arc;

use crate::domain::models::{
    AttestationFailureReason, AttestationRequest, AttestationResult, Selector, TrustDomain,
};
use crate::domain::ports::inbound::attestation::{AttestationError, AttestationUseCase};
use crate::domain::ports::outbound::store::{StoreError, WorkloadStorePort};

/// The attestation service implements the core workload attestation logic.
///
/// Attestation verifies a workload's identity by matching the selectors
/// presented by the workload against the selectors registered for the
/// workload's SPIFFE ID. If all registered selectors are present in the
/// presented selectors, the workload is considered attested.
///
/// The attestation process is:
/// 1. Validate that the SPIFFE ID is well-formed and belongs to the trust domain
/// 2. Look up the workload by SPIFFE ID in the workload store
/// 3. Verify that all the workload's registered selectors are present
///    in the presented selectors
/// 4. Return the attestation result with an expiry timestamp
pub struct AttestationService {
    /// The workload store for looking up registered workloads.
    store: Arc<dyn WorkloadStorePort>,
    /// The attestation TTL in seconds (how long an attestation is valid).
    attestation_ttl_seconds: u64,
}

impl AttestationService {
    /// Creates a new attestation service.
    pub fn new(store: Arc<dyn WorkloadStorePort>, attestation_ttl_seconds: u64) -> Self {
        Self {
            store,
            attestation_ttl_seconds,
        }
    }

    /// Returns the current Unix timestamp in seconds.
    /// In production, this would use a time provider port for testability.
    fn current_timestamp() -> u64 {
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap_or_default()
            .as_secs()
    }

    /// Validates that the SPIFFE ID belongs to the specified trust domain.
    fn validate_trust_domain(
        spiffe_id: &crate::domain::models::SPIFFEID,
        trust_domain: &TrustDomain,
    ) -> Result<(), AttestationFailureReason> {
        if !spiffe_id.belongs_to(trust_domain) {
            return Err(AttestationFailureReason::TrustDomainMismatch);
        }
        Ok(())
    }

    /// Verifies that the presented selectors satisfy the workload's
    /// registered selectors.
    ///
    /// For attestation to succeed, every registered selector must be
    /// present in the presented selectors. The presented selectors may
    /// contain additional selectors not in the registration (this is
    /// expected, as the SPIRE Agent collects all available selectors).
    fn verify_selectors(
        registered_selectors: &[Selector],
        presented_selectors: &[Selector],
    ) -> bool {
        for registered in registered_selectors {
            if !presented_selectors.contains(registered) {
                return false;
            }
        }
        true
    }

    /// Handles store errors by converting them to attestation errors.
    fn handle_store_error(error: StoreError) -> AttestationError {
        match error {
            StoreError::Unavailable(detail) => AttestationError::StoreUnavailable(detail),
            StoreError::Internal(detail) => AttestationError::Internal(detail),
            other => AttestationError::Internal(other.to_string()),
        }
    }
}

impl AttestationUseCase for AttestationService {
    fn attest(&self, request: AttestationRequest) -> Result<AttestationResult, AttestationError> {
        // Step 1: Validate trust domain
        if let Err(reason) = Self::validate_trust_domain(&request.spiffe_id, &request.trust_domain)
        {
            return Ok(AttestationResult::failure(request.spiffe_id, reason));
        }

        // Step 2: Look up the workload by SPIFFE ID
        let workload = match self
            .store
            .get_workload_by_spiffe_id(&request.spiffe_id.as_str())
        {
            Ok(Some(w)) => w,
            Ok(None) => {
                return Ok(AttestationResult::failure(
                    request.spiffe_id,
                    AttestationFailureReason::NoMatchingWorkload,
                ));
            }
            Err(e) => return Err(Self::handle_store_error(e)),
        };

        // Step 3: Check if the workload has been deregistered
        // A workload with no selectors is considered deregistered.
        if workload.selectors.is_empty() {
            return Ok(AttestationResult::failure(
                request.spiffe_id,
                AttestationFailureReason::WorkloadDeregistered,
            ));
        }

        // Step 4: Verify selectors
        if !Self::verify_selectors(&workload.selectors, &request.selectors) {
            return Ok(AttestationResult::failure(
                request.spiffe_id,
                AttestationFailureReason::SelectorMismatch,
            ));
        }

        // Step 5: Mark the workload as attested
        let mut attested_workload = workload;
        attested_workload.mark_attested();
        if let Err(e) = self.store.update_workload(&attested_workload) {
            // Log the error but don't fail the attestation
            // The attestation itself is valid; only the persistence failed
            tracing::warn!(error = %e, "Failed to persist attested workload state");
        }

        // Step 6: Return successful attestation result
        let expires_at = Self::current_timestamp() + self.attestation_ttl_seconds;
        Ok(AttestationResult::success(request.spiffe_id, expires_at))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::domain::models::workload::{Workload, SPIFFEID};

    /// A simple in-memory workload store for testing.
    struct InMemoryWorkloadStore {
        workloads: std::collections::HashMap<String, Workload>,
    }

    impl InMemoryWorkloadStore {
        fn new() -> Self {
            Self {
                workloads: std::collections::HashMap::new(),
            }
        }

        fn add_workload(&mut self, workload: Workload) {
            self.workloads.insert(workload.spiffe_id.as_str(), workload);
        }
    }

    impl WorkloadStorePort for InMemoryWorkloadStore {
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
            _svid: &crate::domain::models::X509SVID,
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
            _serial_number: &str,
            _reason: crate::domain::models::RevocationReason,
            _revoked_by: &str,
            _comment: Option<&str>,
        ) -> Result<crate::domain::models::RevokedSVID, StoreError> {
            Err(StoreError::CertificateNotFound("test".to_string()))
        }
        fn list_revoked(
            &self,
            _trust_domain: &str,
            _sequence_gt: u64,
        ) -> Result<Vec<crate::domain::models::RevokedSVID>, StoreError> {
            Ok(vec![])
        }
        fn is_revoked(&self, _serial_number: &str) -> Result<bool, StoreError> {
            Ok(false)
        }
        fn store_bundle(
            &self,
            _bundle: &crate::domain::models::X509Bundle,
        ) -> Result<(), StoreError> {
            Ok(())
        }
        fn get_bundle(
            &self,
            _trust_domain: &str,
        ) -> Result<Option<crate::domain::models::X509Bundle>, StoreError> {
            Ok(None)
        }
        fn increment_bundle_sequence(&self, _trust_domain: &str) -> Result<u64, StoreError> {
            Ok(1)
        }
    }

    fn create_test_workload(spiffe_id: &str, selectors: Vec<Selector>) -> Workload {
        let id = SPIFFEID::parse(spiffe_id).unwrap();
        let parent_id = SPIFFEID::parse("spiffe://trust.example.org/spire/agent").unwrap();
        Workload::new(
            "w-test".to_string(),
            id,
            parent_id,
            selectors,
            3600,
            vec!["test.trust.example.org".to_string()],
        )
    }

    #[test]
    fn attest_successful() {
        let mut store = InMemoryWorkloadStore::new();
        let workload = create_test_workload(
            "spiffe://trust.example.org/services/gateway",
            vec![
                Selector::k8s_namespace("production"),
                Selector::k8s_label("app", "gateway"),
            ],
        );
        store.add_workload(workload);

        let service = AttestationService::new(Arc::new(store), 300);
        let request = AttestationRequest::new(
            SPIFFEID::parse("spiffe://trust.example.org/services/gateway").unwrap(),
            vec![
                Selector::k8s_namespace("production"),
                Selector::k8s_label("app", "gateway"),
                Selector::unix_uid(1000), // Extra selector is fine
            ],
            TrustDomain::production(),
        );

        let result = service.attest(request).unwrap();
        assert!(result.attested);
    }

    #[test]
    fn attest_selector_mismatch() {
        let mut store = InMemoryWorkloadStore::new();
        let workload = create_test_workload(
            "spiffe://trust.example.org/services/gateway",
            vec![
                Selector::k8s_namespace("production"),
                Selector::k8s_label("app", "gateway"),
            ],
        );
        store.add_workload(workload);

        let service = AttestationService::new(Arc::new(store), 300);
        let request = AttestationRequest::new(
            SPIFFEID::parse("spiffe://trust.example.org/services/gateway").unwrap(),
            vec![
                Selector::k8s_namespace("staging"), // Wrong namespace
                Selector::k8s_label("app", "gateway"),
            ],
            TrustDomain::production(),
        );

        let result = service.attest(request).unwrap();
        assert!(!result.attested);
    }

    #[test]
    fn attest_no_matching_workload() {
        let store = InMemoryWorkloadStore::new();
        let service = AttestationService::new(Arc::new(store), 300);
        let request = AttestationRequest::new(
            SPIFFEID::parse("spiffe://trust.example.org/services/unknown").unwrap(),
            vec![Selector::k8s_namespace("production")],
            TrustDomain::production(),
        );

        let result = service.attest(request).unwrap();
        assert!(!result.attested);
    }

    #[test]
    fn attest_trust_domain_mismatch() {
        let mut store = InMemoryWorkloadStore::new();
        let workload = create_test_workload(
            "spiffe://trust.example.org/services/gateway",
            vec![Selector::k8s_namespace("production")],
        );
        store.add_workload(workload);

        let service = AttestationService::new(Arc::new(store), 300);
        let request = AttestationRequest::new(
            SPIFFEID::parse("spiffe://trust.example.org/services/gateway").unwrap(),
            vec![Selector::k8s_namespace("production")],
            TrustDomain::staging(), // Wrong trust domain
        );

        let result = service.attest(request).unwrap();
        assert!(!result.attested);
    }

    #[test]
    fn verify_selectors_subset_match() {
        let registered = vec![
            Selector::k8s_namespace("production"),
            Selector::k8s_label("app", "gateway"),
        ];
        let presented = vec![
            Selector::k8s_namespace("production"),
            Selector::k8s_label("app", "gateway"),
            Selector::unix_uid(1000),
        ];
        assert!(AttestationService::verify_selectors(
            &registered,
            &presented
        ));
    }

    #[test]
    fn verify_selectors_missing_selector() {
        let registered = vec![
            Selector::k8s_namespace("production"),
            Selector::k8s_label("app", "gateway"),
        ];
        let presented = vec![
            Selector::k8s_namespace("production"),
            // Missing k8s_label selector
        ];
        assert!(!AttestationService::verify_selectors(
            &registered,
            &presented
        ));
    }
}
