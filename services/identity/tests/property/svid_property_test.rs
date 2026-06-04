// ---------------------------------------------------------------------------
// Property-Based Tests: SVID Generation and Attestation
// ---------------------------------------------------------------------------
// Uses proptest to generate random inputs and verify that the domain
// invariants hold for all valid inputs.
// ---------------------------------------------------------------------------

use proptest::prelude::*;
use std::sync::Arc;
use identity_service::domain::models::{
    AttestationRequest, RevocationReason, RevokedSVID,
    Selector, SPIFFEID, TrustDomain, TTLPolicy,
    X509Bundle, X509SVID,
};
use identity_service::domain::ports::inbound::attestation::AttestationUseCase;
use identity_service::domain::ports::outbound::store::{
    StoreError, StoredSVID, WorkloadList, WorkloadStorePort,
};
use identity_service::domain::services::AttestationService;
use identity_service::domain::models::workload::Workload;

// ---- Custom Strategies ----

/// Generates a valid trust domain name.
fn trust_domain_strategy() -> impl Strategy<Value = String> {
    prop_oneof![
        Just("trust.example.org".to_string()),
        Just("trust.staging.example.org".to_string()),
        Just("trust.dev.example.org".to_string()),
    ]
}

/// Generates a valid workload path component.
fn workload_path_strategy() -> impl Strategy<Value = String> {
    prop_oneof![
        Just("/services/gateway".to_string()),
        Just("/services/order".to_string()),
        Just("/services/catalog".to_string()),
        Just("/services/payment".to_string()),
        Just("/services/notification".to_string()),
        Just("/services/analytics".to_string()),
        Just("/spire/agent".to_string()),
    ]
}

/// Generates a valid SPIFFE ID string.
fn spiffe_id_strategy() -> impl Strategy<Value = String> {
    (trust_domain_strategy(), workload_path_strategy())
        .prop_map(|(domain, path)| format!("spiffe://{}/{}", domain, path.trim_start_matches('/')))
}

/// Generates a valid selector.
fn selector_strategy() -> impl Strategy<Value = Selector> {
    prop_oneof![
        Just(Selector::k8s_namespace("production")),
        Just(Selector::k8s_namespace("staging")),
        Just(Selector::k8s_namespace("development")),
        Just(Selector::k8s_label("app", "gateway")),
        Just(Selector::k8s_label("app", "order")),
        Just(Selector::k8s_label("app", "catalog")),
        Just(Selector::unix_uid(1000)),
        Just(Selector::unix_uid(1001)),
        Just(Selector::unix_gid(2000)),
    ]
}

/// Generates a vector of selectors.
fn selectors_strategy() -> impl Strategy<Value = Vec<Selector>> {
    prop::collection::vec(selector_strategy(), 1..5)
}

/// Generates a valid TTL in seconds.
fn ttl_strategy() -> impl Strategy<Value = u64> {
    60..259200u64 // 1 minute to 72 hours
}

/// Generates a serial number string.
#[allow(dead_code)]
fn serial_number_strategy() -> impl Strategy<Value = String> {
    "[0-9a-f]{16}".prop_map(|s| format!("serial-{}", s))
}

// ---- Property Tests ----

proptest! {
    /// SPIFFE ID parsing must be involutory: parse(format(id)) == id
    #[test]
    fn spiffe_id_roundtrip(id in spiffe_id_strategy()) {
        let parsed = SPIFFEID::parse(&id).unwrap();
        prop_assert_eq!(parsed.as_str(), id);
    }

    /// SPIFFE ID must reject invalid formats
    #[test]
    fn spiffe_id_rejects_invalid(id in ".*") {
        let result = SPIFFEID::parse(&id);
        if id.starts_with("spiffe://") && id.matches('/').count() >= 3 {
            // Valid format should parse
            prop_assert!(result.is_ok());
        } else if !id.starts_with("spiffe://") {
            // Invalid format should fail
            prop_assert!(result.is_err());
        }
    }

    /// SPIFFE ID trust domain must match the parsed domain
    #[test]
    fn spiffe_id_trust_domain_consistency(id in spiffe_id_strategy()) {
        let parsed = SPIFFEID::parse(&id).unwrap();
        let domain_str = id
            .strip_prefix("spiffe://")
            .unwrap()
            .split('/')
            .next()
            .unwrap();
        prop_assert_eq!(parsed.trust_domain.name, domain_str);
    }

    /// SVID expiry must be deterministic: expired at T implies expired at T+1
    #[test]
    fn svid_expiry_monotonic(expires_at in 1000u64..10000, now in 0u64..10000) {
        let svid = X509SVID::new(
            "spiffe://trust.example.org/test".to_string(),
            vec![],
            String::new(),
            "serial".to_string(),
            expires_at,
            0,
            vec![],
            "trust.example.org".to_string(),
        );

        if svid.is_expired_at(now) && now < u64::MAX {
            prop_assert!(svid.is_expired_at(now + 1));
        }
    }

    /// SVID remaining TTL must be non-negative
    #[test]
    fn svid_remaining_ttl_non_negative(expires_at in 100u64..10000, now in 0u64..20000) {
        let svid = X509SVID::new(
            "spiffe://trust.example.org/test".to_string(),
            vec![],
            String::new(),
            "serial".to_string(),
            expires_at,
            0,
            vec![],
            "trust.example.org".to_string(),
        );

        let remaining = svid.remaining_ttl(now);
        prop_assert!(remaining <= expires_at);
    }

    /// TTL policy must reject zero TTL
    #[test]
    fn ttl_policy_rejects_zero(ttl in 0u64..1) {
        let policy = TTLPolicy::default();
        prop_assert!(policy.validate_ttl(ttl).is_err());
    }

    /// TTL policy must reject TTLs exceeding the maximum
    #[test]
    fn ttl_policy_rejects_excessive(ttl in 259201u64..500000) {
        let policy = TTLPolicy::default();
        prop_assert!(policy.validate_ttl(ttl).is_err());
    }

    /// TTL policy must accept valid TTLs
    #[test]
    fn ttl_policy_accepts_valid(ttl in ttl_strategy()) {
        let policy = TTLPolicy::default();
        prop_assert!(policy.validate_ttl(ttl).is_ok());
    }

    /// Revocation reason code must be involutory
    #[test]
    fn revocation_reason_roundtrip(code in 0u8..10) {
        let reason = RevocationReason::from_code(code);
        let roundtrip = RevocationReason::from_code(reason.code());
        prop_assert_eq!(reason, roundtrip);
    }

    /// Trust bundle sequence number must be non-zero
    #[test]
    fn trust_bundle_sequence_positive(seq in 1u64..1000000) {
        let bundle = X509Bundle::new(
            "trust.example.org".to_string(),
            vec![vec![1, 2, 3]],
            vec!["cert".to_string()],
            seq,
            seq + 1000,
        );
        prop_assert!(bundle.sequence_number > 0);
    }

    /// Selector parsing must be involutory for valid selectors
    #[test]
    fn selector_parsing_roundtrip(kind in "[a-z0-9]{1,10}", value in "[a-z0-9:=]{1,20}") {
        let selector_str = format!("{}:{}", kind, value);
        if let Ok(parsed) = Selector::parse(&selector_str) {
            prop_assert_eq!(parsed.kind, kind);
            prop_assert_eq!(parsed.value, value);
        }
    }

    /// SVID needs_rotation must be consistent with grace period
    #[test]
    fn svid_rotation_consistency(
        expires_at in 1000u64..10000,
        now in 0u64..15000,
        grace_period in 60u64..600
    ) {
        let svid = X509SVID::new(
            "spiffe://trust.example.org/test".to_string(),
            vec![],
            String::new(),
            "serial".to_string(),
            expires_at,
            0,
            vec![],
            "trust.example.org".to_string(),
        );

        let needs_rotation = svid.needs_rotation(now, grace_period);
        let is_in_grace = svid.is_within_grace_period(now, grace_period);
        let is_expired = svid.is_expired_at(now);

        // needs_rotation is true iff in grace period OR expired
        prop_assert_eq!(needs_rotation, is_in_grace || is_expired);
    }

    /// Emergency revocation reasons must be deterministic
    #[test]
    fn emergency_revocation_deterministic(code in 0u8..10) {
        let reason = RevocationReason::from_code(code);
        let is_emergency = reason.is_emergency();
        // KEY_COMPROMISE (1) and CA_COMPROMISE (2) are emergency
        let expected = code == 1 || code == 2;
        prop_assert_eq!(is_emergency, expected);
    }
}

// ---- Stateful Property Tests ----

/// An in-memory store for stateful property testing.
struct PropertyTestStore {
    workloads: std::collections::HashMap<String, Workload>,
}

impl PropertyTestStore {
    fn new() -> Self {
        Self {
            workloads: std::collections::HashMap::new(),
        }
    }
}

impl WorkloadStorePort for PropertyTestStore {
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
    fn revoke_svid(&self, serial_number: &str, _reason: RevocationReason, _revoked_by: &str, _comment: Option<&str>) -> Result<RevokedSVID, StoreError> {
        Ok(RevokedSVID {
            serial_number: serial_number.to_string(),
            spiffe_id: "spiffe://trust.example.org/test".to_string(),
            reason: RevocationReason::Unspecified,
            revoked_at: 1000,
            revoked_by: "property-test".to_string(),
            comment: None,
            trust_domain: "trust.example.org".to_string(),
        })
    }
    fn list_revoked(&self, _trust_domain: &str, _sequence_gt: u64) -> Result<Vec<RevokedSVID>, StoreError> { Ok(vec![]) }
    fn is_revoked(&self, _serial_number: &str) -> Result<bool, StoreError> { Ok(false) }
    fn store_bundle(&self, _bundle: &X509Bundle) -> Result<(), StoreError> { Ok(()) }
    fn get_bundle(&self, _trust_domain: &str) -> Result<Option<X509Bundle>, StoreError> { Ok(None) }
    fn increment_bundle_sequence(&self, _trust_domain: &str) -> Result<u64, StoreError> { Ok(1) }
}

proptest! {
    /// Attestation must always return a result (never panic)
    /// regardless of the input selectors
    #[test]
    fn attestation_never_panics(
        spiffe_id_str in spiffe_id_strategy(),
        selectors in selectors_strategy(),
        trust_domain in trust_domain_strategy()
    ) {
        let store = PropertyTestStore::new();
        let service = AttestationService::new(Arc::new(store), 300);

        let spiffe_id = SPIFFEID::parse(&spiffe_id_str).unwrap();
        let domain = TrustDomain::new(trust_domain);

        let request = AttestationRequest::new(spiffe_id, selectors, domain);
        let result = service.attest(request);

        // Must return Ok (not panic)
        prop_assert!(result.is_ok());
    }

    /// Attestation for unregistered workload must always fail
    #[test]
    fn attestation_unregistered_always_fails(
        spiffe_id_str in spiffe_id_strategy(),
        selectors in selectors_strategy(),
        trust_domain in trust_domain_strategy()
    ) {
        let store = PropertyTestStore::new();
        let service = AttestationService::new(Arc::new(store), 300);

        let spiffe_id = SPIFFEID::parse(&spiffe_id_str).unwrap();
        let domain = TrustDomain::new(trust_domain.clone());

        // Only test if SPIFFE ID belongs to the trust domain
        if spiffe_id.belongs_to(&domain) {
            let request = AttestationRequest::new(spiffe_id, selectors, domain);
            let result = service.attest(request).unwrap();
            prop_assert!(!result.attested);
        }
    }
}
