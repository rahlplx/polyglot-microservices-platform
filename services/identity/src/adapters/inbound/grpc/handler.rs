// ---------------------------------------------------------------------------
// gRPC Handler Adapter
// ---------------------------------------------------------------------------
// Implements the tonic gRPC service handlers that translate between
// protobuf messages and domain models. This is the primary inbound
// adapter for the Identity service.
// ---------------------------------------------------------------------------

use std::sync::Arc;
use tonic::{Request, Response, Status};

use crate::domain::models::{
    AttestationRequest, RevocationReason, RotationReason, TrustDomain,
};
use crate::domain::models::workload::{Selector, SPIFFEID};
use crate::domain::ports::inbound::{
    AttestationUseCase, GetTrustBundleUseCase, IssueSVIDUseCase,
    RevokeSVIDUseCase, RotateCertificateUseCase,
};

/// The gRPC handler for the Identity service.
///
/// This struct implements the tonic service traits for both the
/// IdentityService and MTLSService defined in the proto schemas.
/// It translates incoming gRPC requests into domain model calls
/// and converts domain results back to protobuf responses.
pub struct IdentityGrpcHandler {
    /// The attestation use case.
    attestation: Arc<dyn AttestationUseCase>,
    /// The SVID issuance use case.
    svid_issuer: Arc<dyn IssueSVIDUseCase>,
    /// The SVID revocation use case.
    svid_revoker: Arc<dyn RevokeSVIDUseCase>,
    /// The certificate rotation use case.
    cert_rotator: Arc<dyn RotateCertificateUseCase>,
    /// The trust bundle use case.
    bundle_provider: Arc<dyn GetTrustBundleUseCase>,
}

impl IdentityGrpcHandler {
    /// Creates a new gRPC handler with the given use case implementations.
    pub fn new(
        attestation: Arc<dyn AttestationUseCase>,
        svid_issuer: Arc<dyn IssueSVIDUseCase>,
        svid_revoker: Arc<dyn RevokeSVIDUseCase>,
        cert_rotator: Arc<dyn RotateCertificateUseCase>,
        bundle_provider: Arc<dyn GetTrustBundleUseCase>,
    ) -> Self {
        Self {
            attestation,
            svid_issuer,
            svid_revoker,
            cert_rotator,
            bundle_provider,
        }
    }

    /// Handles the AttestWorkload RPC.
    pub async fn attest_workload(
        &self,
        request: AttestWorkloadRequest,
    ) -> Result<Response<AttestWorkloadResponse>, Status> {
        // Parse the SPIFFE ID
        let spiffe_id = SPIFFEID::parse(&request.spiffe_id)
            .map_err(|e| Status::invalid_argument(format!("invalid SPIFFE ID: {}", e)))?;

        // Parse the trust domain
        let trust_domain = TrustDomain::new(request.trust_domain);

        // Convert selectors
        let selectors: Vec<Selector> = request
            .selectors
            .iter()
            .map(|(k, v)| Selector::new(k.clone(), v.clone()))
            .collect();

        // Create the domain attestation request
        let attestation_request = AttestationRequest::new(spiffe_id, selectors, trust_domain);

        // Execute the use case
        let result = self
            .attestation
            .attest(attestation_request)
            .map_err(|e| Status::internal(e.to_string()))?;

        // Build the response
        let response = AttestWorkloadResponse {
            attested: result.attested,
            spiffe_id: result.spiffe_id.as_str(),
            expires_at: Some(prost_types::Timestamp {
                seconds: result.expires_at as i64,
                nanos: 0,
            }),
            failure_reason: result
                .failure_reason
                .map(|r| r.to_string())
                .unwrap_or_default(),
        };

        Ok(Response::new(response))
    }

    /// Handles the IssueSVID RPC.
    pub async fn issue_svid(
        &self,
        request: IssueSVIDRequest,
    ) -> Result<Response<IssueSVIDResponse>, Status> {
        let dns_names: Vec<String> = vec![]; // Proto doesn't have dns_names, use default

        let (svid, _bundle) = self
            .svid_issuer
            .issue_svid(
                &request.spiffe_id,
                request.ttl_seconds as u64,
                &dns_names,
                &request.trust_domain,
                if request.csr.is_empty() {
                    None
                } else {
                    Some(&request.csr)
                },
            )
            .map_err(|e| match e {
                crate::domain::ports::inbound::IssueSVIDError::WorkloadNotFound(id) => {
                    Status::not_found(format!("workload not found: {}", id))
                }
                crate::domain::ports::inbound::IssueSVIDError::InvalidSPIFFEID(detail) => {
                    Status::invalid_argument(format!("invalid SPIFFE ID: {}", detail))
                }
                crate::domain::ports::inbound::IssueSVIDError::WorkloadNotAttested(id) => {
                    Status::failed_precondition(format!("workload not attested: {}", id))
                }
                _ => Status::internal(e.to_string()),
            })?;

        let response = IssueSVIDResponse {
            certificate_chain: svid.cert_chain_pem,
            private_key: String::new(), // Never return private key in production gRPC
            expires_at: Some(prost_types::Timestamp {
                seconds: svid.expires_at as i64,
                nanos: 0,
            }),
            spiffe_id: svid.spiffe_id,
        };

        Ok(Response::new(response))
    }

    /// Handles the RevokeSVID RPC.
    pub async fn revoke_svid(
        &self,
        request: RevokeSVIDRequest,
    ) -> Result<Response<RevokeSVIDResponse>, Status> {
        let reason = parse_revocation_reason(&request.reason);

        let revoked = self
            .svid_revoker
            .revoke_svid(
                &request.spiffe_id, // Using spiffe_id as identifier per proto
                reason,
                None,
                "grpc-handler", // TODO: extract from auth context
                &request.trust_domain,
            )
            .map_err(|e| match e {
                crate::domain::ports::inbound::RevokeSVIDError::CertificateNotFound(serial) => {
                    Status::not_found(format!("certificate not found: {}", serial))
                }
                crate::domain::ports::inbound::RevokeSVIDError::AlreadyRevoked(serial) => {
                    Status::already_exists(format!("certificate already revoked: {}", serial))
                }
                _ => Status::internal(e.to_string()),
            })?;

        let response = RevokeSVIDResponse {
            revoked: true,
            revoked_at: Some(prost_types::Timestamp {
                seconds: revoked.revoked_at as i64,
                nanos: 0,
            }),
        };

        Ok(Response::new(response))
    }

    /// Handles the GetTrustBundle RPC.
    pub async fn get_trust_bundle(
        &self,
        request: GetTrustBundleRequest,
    ) -> Result<Response<GetTrustBundleResponse>, Status> {
        let bundle = self
            .bundle_provider
            .get_trust_bundle(&request.trust_domain, false)
            .map_err(|e| match e {
                crate::domain::ports::inbound::TrustBundleError::TrustDomainNotFound(domain) => {
                    Status::not_found(format!("trust domain not found: {}", domain))
                }
                _ => Status::internal(e.to_string()),
            })?;

        let response = GetTrustBundleResponse {
            root_certificates: bundle.root_certs_pem,
            expires_at: Some(prost_types::Timestamp {
                seconds: bundle.expires_at as i64,
                nanos: 0,
            }),
            sequence_number: bundle.sequence_number,
        };

        Ok(Response::new(response))
    }

    /// Handles the ListWorkloads RPC.
    pub async fn list_workloads(
        &self,
        _request: ListWorkloadsRequest,
    ) -> Result<Response<ListWorkloadsResponse>, Status> {
        // This would be delegated to a list workloads use case
        // For now, return an empty response
        let response = ListWorkloadsResponse {
            workloads: vec![],
            next_cursor: String::new(),
        };
        Ok(Response::new(response))
    }

    /// Handles the GetRotationStatus RPC.
    pub async fn get_rotation_status(
        &self,
        request: GetRotationStatusRequest,
    ) -> Result<Response<GetRotationStatusResponse>, Status> {
        // Return a default rotation status
        let response = GetRotationStatusResponse {
            spiffe_id: request.spiffe_id,
            current_expires_at: Some(prost_types::Timestamp {
                seconds: 0,
                nanos: 0,
            }),
            next_rotation_at: Some(prost_types::Timestamp {
                seconds: 0,
                nanos: 0,
            }),
            rotation_strategy: "timed".to_string(),
            grace_period_seconds: 300,
        };
        Ok(Response::new(response))
    }

    /// Handles the ForceRotation RPC.
    pub async fn force_rotation(
        &self,
        request: ForceRotationRequest,
    ) -> Result<Response<ForceRotationResponse>, Status> {
        let result = self
            .cert_rotator
            .rotate_certificate(
                "", // No current serial in force rotation request
                &request.spiffe_id,
                RotationReason::Proactive,
                &request.trust_domain,
            )
            .map_err(|e| Status::internal(e.to_string()))?;

        let response = ForceRotationResponse {
            rotation_initiated: true,
            new_expiry: Some(prost_types::Timestamp {
                seconds: result.new_svid.expires_at as i64,
                nanos: 0,
            }),
        };

        Ok(Response::new(response))
    }
}

/// Parses a revocation reason from a string representation.
fn parse_revocation_reason(reason: &str) -> RevocationReason {
    match reason.to_uppercase().as_str() {
        "KEY_COMPROMISE" => RevocationReason::KeyCompromise,
        "CA_COMPROMISE" => RevocationReason::CACompromise,
        "AFFILIATION_CHANGED" => RevocationReason::AffiliationChanged,
        "SUPERSEDED" => RevocationReason::Superseded,
        "CESSATION_OF_OPERATION" => RevocationReason::CessationOfOperation,
        "CERTIFICATE_HOLD" => RevocationReason::CertificateHold,
        "REMOVE_FROM_CRL" => RevocationReason::RemoveFromCRL,
        "PRIVILEGE_WITHDRAWN" => RevocationReason::PrivilegeWithdrawn,
        _ => RevocationReason::Unspecified,
    }
}

// ---------------------------------------------------------------------------
// Protobuf message types (hand-defined until code generation is configured)
// ---------------------------------------------------------------------------
// These structs mirror the proto definitions and will be replaced by
// generated code once the build.rs tonic-build configuration is set up.

#[derive(Debug, Clone)]
pub struct AttestWorkloadRequest {
    pub spiffe_id: String,
    pub selectors: std::collections::HashMap<String, String>,
    pub trust_domain: String,
}

#[derive(Debug, Clone)]
pub struct AttestWorkloadResponse {
    pub attested: bool,
    pub spiffe_id: String,
    pub expires_at: Option<prost_types::Timestamp>,
    pub failure_reason: String,
}

#[derive(Debug, Clone)]
pub struct IssueSVIDRequest {
    pub spiffe_id: String,
    pub ttl_seconds: i64,
    pub csr: Vec<u8>,
    pub trust_domain: String,
}

#[derive(Debug, Clone)]
pub struct IssueSVIDResponse {
    pub certificate_chain: String,
    pub private_key: String,
    pub expires_at: Option<prost_types::Timestamp>,
    pub spiffe_id: String,
}

#[derive(Debug, Clone)]
pub struct RevokeSVIDRequest {
    pub spiffe_id: String,
    pub reason: String,
    pub trust_domain: String,
}

#[derive(Debug, Clone)]
pub struct RevokeSVIDResponse {
    pub revoked: bool,
    pub revoked_at: Option<prost_types::Timestamp>,
}

#[derive(Debug, Clone)]
pub struct GetTrustBundleRequest {
    pub trust_domain: String,
}

#[derive(Debug, Clone)]
pub struct GetTrustBundleResponse {
    pub root_certificates: Vec<String>,
    pub expires_at: Option<prost_types::Timestamp>,
    pub sequence_number: u64,
}

#[derive(Debug, Clone)]
pub struct ListWorkloadsRequest {
    pub trust_domain: String,
    pub cursor: String,
    pub page_size: i32,
}

#[derive(Debug, Clone)]
pub struct ListWorkloadsResponse {
    pub workloads: Vec<WorkloadEntry>,
    pub next_cursor: String,
}

#[derive(Debug, Clone)]
pub struct WorkloadEntry {
    pub spiffe_id: String,
    pub parent_id: String,
    pub selectors: std::collections::HashMap<String, String>,
    pub ttl_seconds: i64,
    pub attested: bool,
}

#[derive(Debug, Clone)]
pub struct GetRotationStatusRequest {
    pub spiffe_id: String,
    pub trust_domain: String,
}

#[derive(Debug, Clone)]
pub struct GetRotationStatusResponse {
    pub spiffe_id: String,
    pub current_expires_at: Option<prost_types::Timestamp>,
    pub next_rotation_at: Option<prost_types::Timestamp>,
    pub rotation_strategy: String,
    pub grace_period_seconds: i64,
}

#[derive(Debug, Clone)]
pub struct ForceRotationRequest {
    pub spiffe_id: String,
    pub trust_domain: String,
    pub reason: String,
}

#[derive(Debug, Clone)]
pub struct ForceRotationResponse {
    pub rotation_initiated: bool,
    pub new_expiry: Option<prost_types::Timestamp>,
}
