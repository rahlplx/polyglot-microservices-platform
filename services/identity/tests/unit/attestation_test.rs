// ---------------------------------------------------------------------------
// Unit Tests: Attestation Domain Logic
// ---------------------------------------------------------------------------
// Tests the core attestation domain service with mock implementations
// of the outbound ports. These tests verify the business rules without
// any infrastructure dependencies.
// ---------------------------------------------------------------------------

use std::sync::Arc;
use identity_service::domain::models::{
    AttestationFailureReason, AttestationRequest, AttestationResult,
    Selector, SPIFFEID, TrustDomain, Workload,
};
use identity_service::domain::ports::inbound::attestation::AttestationUseCase;
use identity_service::domain::ports::outbound::store::{
    StoreError, StoredSVID, WorkloadList, WorkloadStorePort,
};
use std::sync::Arc;
use identity_service::domain::models::{
    RevocationReason, RevokedSVID, X509Bundle, X509SVID,
};
use identity_service::domain::services::AttestationService;

/// A thread-safe in-memory workload store for testing.
struct InMemoryWorkloadStore {
    workloads: std::collections::HashMap<String, Workload>,
}

impl InMemoryWorkloadStore {
    fn new() -> Self {
        Self {
            workloads: std::collections::HashMap::new(),
        }
    }

    fn insert(&mut self, workload: Workload) {
        self.workloads.insert(workload.spiffe_id.as_str(), workload);
    }
}

impl WorkloadStorePort for InMemoryWorkloadStore {
    fn register_workload(&self, _workload: &Workload) -> Result<(), StoreError> { Ok(()) }
    fn get_workload(&self, _workload_id: &str) -> Result<Option<Workload>, StoreError> { Ok(None) }
    fn get_workloads_by_selector(&self, _selectors: &[Selector], _trust_domain: &str) -> Result<Vec<Workload>, StoreError> { Ok(vec![]) }
    fn get_workload_by_spiffe_id(&self, spiffe_id: &str) -> Result<Option<Workload>, StoreError> {
        Ok(self.workloads.get(spiffe_id).cloned())
    }
    fn update_workload(&self, _workload: &Workload) -> Result<(), StoreError> { Ok(()) }
    fn delete_workload(&self, _workload_id: &str) -> Result<(), StoreError> { Ok(()) }
    fn list_workloads(&self, _trust_domain: &str, _cursor: Option<&str>, _page_size: i32) -> Result<WorkloadList, StoreError> {
        Ok(WorkloadList { workloads: vec![], next_cursor: None })
    }
    fn store_svid(&self, _svid: &X509SVID, _workload_id: &str, _encrypted_private_key: &[u8]) -> Result<(), StoreError> { Ok(()) }
    fn get_svid(&self, _serial_number: &str) -> Result<Option<StoredSVID>, StoreError> { Ok(None) }
    fn get_active_svid_for_workload(&self, _workload_id: &str) -> Result<Option<StoredSVID>, StoreError> { Ok(None) }
    fn revoke_svid(&self, _serial_number: &str, _reason: RevocationReason, _revoked_by: &str, _comment: Option<&str>) -> Result<RevokedSVID, StoreError> {
        Err(StoreError::CertificateNotFound("test".to_string()))
    }
    fn list_revoked(&self, _trust_domain: &str, _sequence_gt: u64) -> Result<Vec<RevokedSVID>, StoreError> { Ok(vec![]) }
    fn is_revoked(&self, _serial_number: &str) -> Result<bool, StoreError> { Ok(false) }
    fn store_bundle(&self, _bundle: &X509Bundle) -> Result<(), StoreError> { Ok(()) }
    fn get_bundle(&self, _trust_domain: &str) -> Result<Option<X509Bundle>, StoreError> { Ok(None) }
    fn increment_bundle_sequence(&self, _trust_domain: &str) -> Result<u64, StoreError> { Ok(1) }
}

fn create_gateway_workload() -> Workload {
    let spiffe_id = SPIFFEID::parse("spiffe://trust.example.org/services/gateway").unwrap();
    let parent_id = SPIFFEID::parse("spiffe://trust.example.org/spire/agent/k8s/prod").unwrap();
    let mut workload = Workload::new(
        "w-gateway-001".to_string(),
        spiffe_id,
        parent_id,
        vec![
            Selector::k8s_namespace("production"),
            Selector::k8s_label("app", "gateway"),
            Selector::k8s_label("version", "v1"),
        ],
        3600,
        vec!["gateway.trust.example.org".to_string()],
    );
    workload.mark_attested();
    workload
}

fn create_order_workload() -> Workload {
    let spiffe_id = SPIFFEID::parse("spiffe://trust.example.org/services/order").unwrap();
    let parent_id = SPIFFEID::parse("spiffe://trust.example.org/spire/agent/k8s/prod").unwrap();
    let mut workload = Workload::new(
        "w-order-001".to_string(),
        spiffe_id,
        parent_id,
        vec![
            Selector::k8s_namespace("production"),
            Selector::k8s_label("app", "order"),
        ],
        3600,
        vec!["order.trust.example.org".to_string()],
    );
    workload.mark_attested();
    workload
}

// ---- Test Cases ----

#[test]
fn attestation_succeeds_with_matching_selectors() {
    let mut store = InMemoryWorkloadStore::new();
    store.insert(create_gateway_workload());

    let service = AttestationService::new(Arc::new(store), 300);
    let request = AttestationRequest::new(
        SPIFFEID::parse("spiffe://trust.example.org/services/gateway").unwrap(),
        vec![
            Selector::k8s_namespace("production"),
            Selector::k8s_label("app", "gateway"),
            Selector::k8s_label("version", "v1"),
            Selector::unix_uid(1000), // Extra selector is allowed
        ],
        TrustDomain::production(),
    );

    let result = service.attest(request).unwrap();
    assert!(result.attested);
    assert!(result.failure_reason.is_none());
}

#[test]
fn attestation_fails_with_missing_selector() {
    let mut store = InMemoryWorkloadStore::new();
    store.insert(create_gateway_workload());

    let service = AttestationService::new(Arc::new(store), 300);
    let request = AttestationRequest::new(
        SPIFFEID::parse("spiffe://trust.example.org/services/gateway").unwrap(),
        vec![
            Selector::k8s_namespace("production"),
            // Missing Selector::k8s_label("app", "gateway")
        ],
        TrustDomain::production(),
    );

    let result = service.attest(request).unwrap();
    assert!(!result.attested);
    assert_eq!(
        result.failure_reason,
        Some(AttestationFailureReason::SelectorMismatch)
    );
}

#[test]
fn attestation_fails_for_unregistered_workload() {
    let store = InMemoryWorkloadStore::new();
    let service = AttestationService::new(Arc::new(store), 300);

    let request = AttestationRequest::new(
        SPIFFEID::parse("spiffe://trust.example.org/services/unknown").unwrap(),
        vec![Selector::k8s_namespace("production")],
        TrustDomain::production(),
    );

    let result = service.attest(request).unwrap();
    assert!(!result.attested);
    assert_eq!(
        result.failure_reason,
        Some(AttestationFailureReason::NoMatchingWorkload)
    );
}

#[test]
fn attestation_fails_for_trust_domain_mismatch() {
    let mut store = InMemoryWorkloadStore::new();
    store.insert(create_gateway_workload());

    let service = AttestationService::new(Arc::new(store), 300);
    let request = AttestationRequest::new(
        SPIFFEID::parse("spiffe://trust.example.org/services/gateway").unwrap(),
        vec![Selector::k8s_namespace("production")],
        TrustDomain::staging(), // Wrong trust domain
    );

    let result = service.attest(request).unwrap();
    assert!(!result.attested);
    assert_eq!(
        result.failure_reason,
        Some(AttestationFailureReason::TrustDomainMismatch)
    );
}

#[test]
fn attestation_succeeds_for_different_workloads_in_same_domain() {
    let mut store = InMemoryWorkloadStore::new();
    store.insert(create_gateway_workload());
    store.insert(create_order_workload());

    let service = AttestationService::new(Arc::new(store), 300);

    // Gateway workload
    let gateway_request = AttestationRequest::new(
        SPIFFEID::parse("spiffe://trust.example.org/services/gateway").unwrap(),
        vec![
            Selector::k8s_namespace("production"),
            Selector::k8s_label("app", "gateway"),
            Selector::k8s_label("version", "v1"),
        ],
        TrustDomain::production(),
    );
    assert!(service.attest(gateway_request).unwrap().attested);

    // Order workload
    let order_request = AttestationRequest::new(
        SPIFFEID::parse("spiffe://trust.example.org/services/order").unwrap(),
        vec![
            Selector::k8s_namespace("production"),
            Selector::k8s_label("app", "order"),
        ],
        TrustDomain::production(),
    );
    assert!(service.attest(order_request).unwrap().attested);
}

#[test]
fn attestation_fails_for_empty_selectors() {
    let mut store = InMemoryWorkloadStore::new();
    let spiffe_id = SPIFFEID::parse("spiffe://trust.example.org/services/empty").unwrap();
    let parent_id = SPIFFEID::parse("spiffe://trust.example.org/spire/agent").unwrap();
    // Workload with no selectors is considered deregistered
    let workload = Workload::new(
        "w-empty".to_string(),
        spiffe_id,
        parent_id,
        vec![], // Empty selectors
        3600,
        vec![],
    );
    store.insert(workload);

    let service = AttestationService::new(Arc::new(store), 300);
    let request = AttestationRequest::new(
        SPIFFEID::parse("spiffe://trust.example.org/services/empty").unwrap(),
        vec![],
        TrustDomain::production(),
    );

    let result = service.attest(request).unwrap();
    assert!(!result.attested);
    assert_eq!(
        result.failure_reason,
        Some(AttestationFailureReason::WorkloadDeregistered)
    );
}

#[test]
fn spiffe_id_parsing_roundtrip() {
    let ids = vec![
        "spiffe://trust.example.org/services/gateway",
        "spiffe://trust.staging.example.org/services/order",
        "spiffe://trust.dev.example.org/services/test/suite",
    ];

    for id_str in ids {
        let parsed = SPIFFEID::parse(id_str).unwrap();
        assert_eq!(parsed.as_str(), id_str);
    }
}

#[test]
fn selector_parsing() {
    let selector = Selector::parse("k8s:ns:production").unwrap();
    assert_eq!(selector.kind, "k8s");
    assert_eq!(selector.value, "ns:production");
}

#[test]
fn trust_domain_validation() {
    assert!(TrustDomain::production().is_valid());
    assert!(TrustDomain::staging().is_valid());
    assert!(TrustDomain::development().is_valid());
    assert!(!TrustDomain::new("invalid.domain".to_string()).is_valid());
}

#[test]
fn attestation_has_expiry() {
    let mut store = InMemoryWorkloadStore::new();
    store.insert(create_gateway_workload());

    let ttl = 300u64;
    let service = AttestationService::new(Arc::new(store), ttl);
    let request = AttestationRequest::new(
        SPIFFEID::parse("spiffe://trust.example.org/services/gateway").unwrap(),
        vec![
            Selector::k8s_namespace("production"),
            Selector::k8s_label("app", "gateway"),
            Selector::k8s_label("version", "v1"),
        ],
        TrustDomain::production(),
    );

    let result = service.attest(request).unwrap();
    assert!(result.attested);
    assert!(result.expires_at > 0);
}
