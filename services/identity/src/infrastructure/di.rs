// ---------------------------------------------------------------------------
// Infrastructure: Dependency Injection Wiring
// ---------------------------------------------------------------------------
// Wires together all the domain services, outbound adapters, and
// inbound adapters. This is the composition root of the application.
// ---------------------------------------------------------------------------

use std::sync::Arc;

use crate::adapters::inbound::grpc::handler::IdentityGrpcHandler;
use crate::adapters::outbound::crypto::RingCryptoAdapter;
use crate::adapters::outbound::observability::OTelObservabilityAdapter;
use crate::adapters::outbound::persistence::PostgresWorkloadStore;
use crate::adapters::outbound::spire::SPIREAgentClient;
use crate::domain::models::TTLPolicy;
use crate::domain::ports::inbound::{
    AttestationUseCase, GetTrustBundleUseCase, IssueSVIDUseCase,
    RevokeSVIDUseCase, RotateCertificateUseCase,
};
use crate::domain::ports::outbound::ca::CertificateAuthorityPort;
use crate::domain::services::{AttestationService, CertificateRotationService, SVIDService};
use crate::infrastructure::config::Config;

/// The application container that holds all wired dependencies.
///
/// This struct is the composition root of the hexagonal architecture.
/// It creates and wires together all the components:
/// - Outbound adapters (SPIRE client, Postgres store, Ring crypto, OTel)
/// - Domain services (AttestationService, SVIDService, RotationService)
/// - Inbound adapters (gRPC handler)
pub struct AppContainer {
    /// The attestation use case.
    pub attestation: Arc<dyn AttestationUseCase>,
    /// The SVID issuance use case.
    pub svid_issuer: Arc<dyn IssueSVIDUseCase>,
    /// The SVID revocation use case.
    pub svid_revoker: Arc<dyn RevokeSVIDUseCase>,
    /// The certificate rotation use case.
    pub cert_rotator: Arc<dyn RotateCertificateUseCase>,
    /// The trust bundle use case.
    pub bundle_provider: Arc<dyn GetTrustBundleUseCase>,
    /// The gRPC handler.
    pub grpc_handler: IdentityGrpcHandler,
    /// The observability adapter.
    pub observability: Arc<OTelObservabilityAdapter>,
}

impl AppContainer {
    /// Wires together all application dependencies.
    ///
    /// This method creates the full dependency graph:
    /// 1. Outbound adapters (ports implementations)
    /// 2. Domain services (use case implementations)
    /// 3. Inbound adapters (gRPC handler)
    pub async fn wire(config: &Config) -> Result<Self, DIError> {
        tracing::info!("Wiring application dependencies...");

        // --- Outbound Adapters ---

        // Observability adapter (initialized first for tracing)
        let observability = Arc::new(OTelObservabilityAdapter::new(
            "identity-service".to_string(),
            env!("CARGO_PKG_VERSION").to_string(),
            config.otlp_endpoint.clone(),
        ));

        // Crypto adapter (ring-based in-memory CA)
        let crypto_adapter = Arc::new(RingCryptoAdapter::new(
            config.trust_domain.clone(),
            config.master_key.clone(),
        ));

        // Persistence adapter (PostgreSQL)
        let persistence_adapter = if config.feature_postgres_store {
            let pool = sqlx::postgres::PgPoolOptions::new()
                .max_connections(config.database_max_connections)
                .min_connections(config.database_min_connections)
                .connect(&config.database_url)
                .await
                .map_err(|e| DIError::DatabaseConnectionFailed(e.to_string()))?;

            let store = PostgresWorkloadStore::new(pool);
            store
                .migrate()
                .await
                .map_err(|e| DIError::MigrationFailed(e.to_string()))?;

            Arc::new(store) as Arc<dyn crate::domain::ports::outbound::store::WorkloadStorePort>
        } else {
            tracing::warn!("PostgreSQL store disabled, using disconnected store");
            Arc::new(PostgresWorkloadStore::disconnected())
                as Arc<dyn crate::domain::ports::outbound::store::WorkloadStorePort>
        };

        // SPIRE Agent client adapter
        let _spire_client = if config.feature_spire_client {
            Some(SPIREAgentClient::new(
                config.spire_agent_socket.clone(),
                config.trust_domain.clone(),
            ))
        } else {
            None
        };

        // --- TTL Policy ---
        let ttl_policy = TTLPolicy {
            max_ttl_seconds: config.max_ttl_seconds,
            default_production_ttl_seconds: config.default_production_ttl,
            default_staging_ttl_seconds: config.default_staging_ttl,
            default_development_ttl_seconds: config.default_development_ttl,
            grace_period_seconds: config.grace_period_seconds,
        };

        // --- Domain Services ---
        let attestation_service = Arc::new(AttestationService::new(
            persistence_adapter.clone(),
            config.attestation_ttl_seconds,
        ));

        let crypto_adapter_as_ca: Arc<dyn CertificateAuthorityPort> = crypto_adapter.clone();
        let svid_service = Arc::new(SVIDService::new(
            persistence_adapter.clone(),
            crypto_adapter_as_ca,
            ttl_policy.clone(),
        ));

        let rotation_service = Arc::new(CertificateRotationService::new(
            persistence_adapter.clone(),
            crypto_adapter.clone(),
            ttl_policy,
        ));

        // --- Inbound Adapters ---
        let grpc_handler = IdentityGrpcHandler::new(
            attestation_service.clone(),
            svid_service.clone() as Arc<dyn IssueSVIDUseCase>,
            svid_service.clone() as Arc<dyn RevokeSVIDUseCase>,
            rotation_service.clone() as Arc<dyn RotateCertificateUseCase>,
            svid_service.clone() as Arc<dyn GetTrustBundleUseCase>,
        );

        tracing::info!("Application dependencies wired successfully");

        Ok(Self {
            attestation: attestation_service,
            svid_issuer: svid_service.clone(),
            svid_revoker: svid_service.clone(),
            cert_rotator: rotation_service,
            bundle_provider: svid_service,
            grpc_handler,
            observability,
        })
    }
}

/// Errors that can occur during dependency injection wiring.
#[derive(Debug)]
pub enum DIError {
    /// Failed to connect to the database.
    DatabaseConnectionFailed(String),
    /// Failed to run database migrations.
    MigrationFailed(String),
    /// Failed to initialize observability.
    ObservabilityInitFailed(String),
    /// Failed to connect to the SPIRE Agent.
    SPIREConnectionFailed(String),
    /// A required configuration value is missing.
    MissingConfig(String),
}

impl std::fmt::Display for DIError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::DatabaseConnectionFailed(detail) => {
                write!(f, "database connection failed: {}", detail)
            }
            Self::MigrationFailed(detail) => {
                write!(f, "migration failed: {}", detail)
            }
            Self::ObservabilityInitFailed(detail) => {
                write!(f, "observability init failed: {}", detail)
            }
            Self::SPIREConnectionFailed(detail) => {
                write!(f, "SPIRE Agent connection failed: {}", detail)
            }
            Self::MissingConfig(detail) => {
                write!(f, "missing configuration: {}", detail)
            }
        }
    }
}

impl std::error::Error for DIError {}
