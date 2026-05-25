// ---------------------------------------------------------------------------
// Contract Tests: Identity Service gRPC API
// ---------------------------------------------------------------------------
// Verifies that the Identity service conforms to its gRPC contract
// as defined in the proto schemas. These tests validate the API
// behavior from a consumer's perspective.
// ---------------------------------------------------------------------------

use identity_service::domain::models::{
    AttestationRequest, AttestationResult, RevocationReason, RevokedSVID, RotationReason,
    Selector, SPIFFEID, TrustDomain, TTLPolicy, Workload, X509Bundle, X509SVID,
};
use identity_service::domain::ports::inbound::{
    AttestationUseCase, GetTrustBundleUseCase, IssueSVIDUseCase,
    RevokeSVIDUseCase, RotateCertificateUseCase,
};
use identity_service::domain::ports::outbound::ca::{
    CAError, CertificateAuthorityPort, GeneratedSVID, SignedSVID,
};
use identity_service::domain::ports::outbound::store::{
    StoreError, StoredSVID, WorkloadList, WorkloadStorePort,
};
use identity_service::domain::services::{AttestationService, CertificateRotationService, SVIDService};
use identity_service::adapters::inbound::grpc::handler::IdentityGrpcHandler;

use std::sync::Arc;

// ---- Mock Implementations for Contract Testing ----

struct ContractTestCA;

impl CertificateAuthorityPort for ContractTestCA {
    fn sign_svid(&self, _csr_der: &[u8], spiffe_id: &str, _dns_names: &[String], ttl_seconds: u64) -> Result<SignedSVID, CAError> {
        Ok(SignedSVID {
            cert_chain_der: vec![vec![0x30, 0x82, 0x01]], // Fake DER
            cert_chain_pem: format!("-----BEGIN CERTIFICATE-----\n{}\n-----END CERTIFICATE-----", spiffe_id.len()),
            serial_number: format!("{:016x}", ttl_seconds),
            not_before: 1000,
            not_after: 1000 + ttl_seconds,
        })
    }

    fn generate_and_sign_svid(&self, spiffe_id: &str, dns_names: &[String], ttl_seconds: u64) -> Result<GeneratedSVID, CAError> {
        Ok(GeneratedSVID {
            svid: self.sign_svid(&[], spiffe_id, dns_names, ttl_seconds)?,
            private_key_der: vec![0x04, 0x82], // Fake encrypted key
            private_key_pem: "-----BEGIN ENCRYPTED PRIVATE KEY-----\nMOCK\n-----END ENCRYPTED PRIVATE KEY-----".to_string(),
        })
    }

    fn get_trust_bundle(&self, trust_domain: &str) -> Result<X509Bundle, CAError> {
        Ok(X509Bundle::new(
            trust_domain.to_string(),
            vec![vec![0x30, 0x82]], // Fake root cert DER
            vec!["-----BEGIN CERTIFICATE-----\nROOT\n-----END CERTIFICATE-----".to_string()],
            1,
            99999,
        ))
    }

    fn rotate_ca_key(&self, _trust_domain: &str) -> Result<(), CAError> { Ok(()) }
    fn is_ca_rotation_in_progress(&self) -> bool { false }
}

struct ContractTestStore {
    workloads: std::collections::HashMap<String, Workload>,
    revoked_serials: std::collections::HashSet<String>,
    bundle_sequence: std::sync::atomic::AtomicU64,
}

impl ContractTestStore {
    fn new() -> Self {
        Self {
            workloads: std::collections::HashMap::new(),
            revoked_serials: std::collections::HashSet::new(),
            bundle_sequence: std::sync::atomic::AtomicU64::new(1),
        }
    }

    fn add_attested_workload(&mut self, spiffe_id: &str, selectors: Vec<Selector>) {
        let id = SPIFFEID::parse(spiffe_id).unwrap();
        let parent_id = SPIFFEID::parse("spiffe://trust.example.org/spire/agent").unwrap();
        let mut w = Workload::new(
            format!("w-{}", spiffe_id.len()),
            id, parent_id, selectors, 3600,
            vec!["svc.trust.example.org".to_string()],
        );
        w.mark_attested();
        self.workloads.insert(spiffe_id.to_string(), w);
    }
}

impl WorkloadStorePort for ContractTestStore {
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
    fn revoke_svid(&self, serial_number: &str, reason: RevocationReason, _revoked_by: &str, _comment: Option<&str>) -> Result<RevokedSVID, StoreError> {
        if self.revoked_serials.contains(serial_number) {
            return Err(StoreError::AlreadyRevoked(serial_number.to_string()));
        }
        Ok(RevokedSVID {
            serial_number: serial_number.to_string(),
            spiffe_id: "spiffe://trust.example.org/test".to_string(),
            reason,
            revoked_at: 1000,
            revoked_by: "contract-test".to_string(),
            comment: None,
            trust_domain: "trust.example.org".to_string(),
        })
    }
    fn list_revoked(&self, _trust_domain: &str, _sequence_gt: u64) -> Result<Vec<RevokedSVID>, StoreError> { Ok(vec![]) }
    fn is_revoked(&self, serial_number: &str) -> Result<bool, StoreError> { Ok(self.revoked_serials.contains(serial_number)) }
    fn store_bundle(&self, _bundle: &X509Bundle) -> Result<(), StoreError> { Ok(()) }
    fn get_bundle(&self, _trust_domain: &str) -> Result<Option<X509Bundle>, StoreError> { Ok(None) }
    fn increment_bundle_sequence(&self, _trust_domain: &str) -> Result<u64, StoreError> {
        Ok(self.bundle_sequence.fetch_add(1, std::sync::atomic::Ordering::SeqCst) + 1)
    }
}

// ---- Contract Test Cases ----

#[test]
fn contract_attest_workload_returns_attested_flag() {
    let mut store = ContractTestStore::new();
    store.add_attested_workload(
        "spiffe://trust.example.org/services/gateway",
        vec![Selector::k8s_namespace("production"), Selector::k8s_label("app", "gateway")],
    );

    let service = AttestationService::new(Arc::new(store), 300);
    let request = AttestationRequest::new(
        SPIFFEID::parse("spiffe://trust.example.org/services/gateway").unwrap(),
        vec![Selector::k8s_namespace("production"), Selector::k8s_label("app", "gateway")],
        TrustDomain::production(),
    );

    let result = service.attest(request).unwrap();
    // Contract: attestation result must include attested boolean
    assert!(result.attested);
    // Contract: attestation result must include spiffe_id
    assert_eq!(result.spiffe_id.as_str(), "spiffe://trust.example.org/services/gateway");
    // Contract: attestation result must include expires_at
    assert!(result.expires_at > 0);
}

#[test]
fn contract_attest_workload_failure_includes_reason() {
    let store = ContractTestStore::new();
    let service = AttestationService::new(Arc::new(store), 300);

    let request = AttestationRequest::new(
        SPIFFEID::parse("spiffe://trust.example.org/services/nonexistent").unwrap(),
        vec![Selector::k8s_namespace("production")],
        TrustDomain::production(),
    );

    let result = service.attest(request).unwrap();
    // Contract: failed attestation must have attested=false
    assert!(!result.attested);
    // Contract: failed attestation must include failure_reason
    assert!(result.failure_reason.is_some());
}

#[test]
fn contract_issue_svid_returns_certificate_chain() {
    let mut store = ContractTestStore::new();
    store.add_attested_workload(
        "spiffe://trust.example.org/services/gateway",
        vec![Selector::k8s_namespace("production")],
    );

    let service = SVIDService::new(
        Arc::new(store),
        Arc::new(ContractTestCA),
        TTLPolicy::default(),
    );

    let result = service.issue_svid(
        "spiffe://trust.example.org/services/gateway",
        3600,
        &["gateway.trust.example.org".to_string()],
        "trust.example.org",
        None,
    );

    // Contract: issue_svid must return (X509SVID, X509Bundle)
    let (svid, bundle) = result.unwrap();
    // Contract: SVID must contain spiffe_id
    assert!(!svid.spiffe_id.is_empty());
    // Contract: SVID must contain certificate chain
    assert!(!svid.cert_chain_pem.is_empty());
    // Contract: SVID must contain expiry
    assert!(svid.expires_at > 0);
    // Contract: Bundle must contain trust_domain
    assert!(!bundle.trust_domain.is_empty());
}

#[test]
fn contract_issue_svid_rejects_unregistered_workload() {
    let store = ContractTestStore::new();

    let service = SVIDService::new(
        Arc::new(store),
        Arc::new(ContractTestCA),
        TTLPolicy::default(),
    );

    let result = service.issue_svid(
        "spiffe://trust.example.org/services/unknown",
        3600,
        &[],
        "trust.example.org",
        None,
    );

    // Contract: issuing for unregistered workload must return error
    assert!(result.is_err());
}

#[test]
fn contract_revoke_svid_returns_revoked_status() {
    let store = ContractTestStore::new();

    let service = SVIDService::new(
        Arc::new(store),
        Arc::new(ContractTestCA),
        TTLPolicy::default(),
    );

    let result = service.revoke_svid(
        "serial-123",
        RevocationReason::KeyCompromise,
        Some("suspected compromise"),
        "admin",
        "trust.example.org",
    );

    // Contract: revocation must return RevokedSVID
    let revoked = result.unwrap();
    assert!(!revoked.serial_number.is_empty());
    assert!(revoked.revoked_at > 0);
}

#[test]
fn contract_get_trust_bundle_returns_root_certs() {
    let store = ContractTestStore::new();

    let service = SVIDService::new(
        Arc::new(store),
        Arc::new(ContractTestCA),
        TTLPolicy::default(),
    );

    let result = service.get_trust_bundle("trust.example.org", false);

    // Contract: get_trust_bundle must return X509Bundle
    let bundle = result.unwrap();
    assert_eq!(bundle.trust_domain, "trust.example.org");
    assert!(bundle.sequence_number >= 1);
}

#[test]
fn contract_ttl_policy_enforces_max() {
    let policy = TTLPolicy::default();

    // Contract: TTL exceeding max must be rejected
    assert!(policy.validate_ttl(0).is_err());
    assert!(policy.validate_ttl(300000).is_err());
    // Contract: TTL within range must be accepted
    assert!(policy.validate_ttl(3600).is_ok());
    assert!(policy.validate_ttl(259200).is_ok());
}

#[test]
fn contract_revocation_reason_is_emergency() {
    // Contract: KEY_COMPROMISE and CA_COMPROMISE are emergency reasons
    assert!(RevocationReason::KeyCompromise.is_emergency());
    assert!(RevocationReason::CACompromise.is_emergency());
    // Contract: other reasons are not emergency
    assert!(!RevocationReason::Superseded.is_emergency());
    assert!(!RevocationReason::Unspecified.is_emergency());
}
