// ---------------------------------------------------------------------------
// Infrastructure: Configuration
// ---------------------------------------------------------------------------
// Loads configuration from environment variables and feature flags.
// All configuration values have sensible defaults for local development.
// ---------------------------------------------------------------------------

use std::env;

/// The Identity service configuration.
///
/// Configuration is loaded from environment variables with sensible
/// defaults. In production, these are set via Kubernetes ConfigMaps
/// and Secrets.
#[derive(Debug, Clone)]
pub struct Config {
    // --- Server ---
    /// The gRPC server bind address (default: "0.0.0.0:9090").
    pub grpc_bind_addr: String,
    /// The HTTP health check bind address (default: "0.0.0.0:8080").
    pub http_bind_addr: String,

    // --- Database ---
    /// The PostgreSQL connection string.
    pub database_url: String,
    /// Maximum number of database connections in the pool.
    pub database_max_connections: u32,
    /// Minimum number of idle database connections.
    pub database_min_connections: u32,

    // --- SPIRE Agent ---
    /// The SPIRE Agent Workload API socket path.
    pub spire_agent_socket: String,
    /// The trust domain for this Identity service.
    pub trust_domain: String,

    // --- Certificate Policy ---
    /// Maximum SVID TTL in seconds (default: 259200 / 72 hours).
    pub max_ttl_seconds: u64,
    /// Default SVID TTL for production (default: 3600 / 1 hour).
    pub default_production_ttl: u64,
    /// Default SVID TTL for staging (default: 14400 / 4 hours).
    pub default_staging_ttl: u64,
    /// Default SVID TTL for development (default: 86400 / 24 hours).
    pub default_development_ttl: u64,
    /// Grace period before SVID expiry for rotation (default: 300 / 5 minutes).
    pub grace_period_seconds: u64,
    /// Attestation TTL in seconds (default: 300 / 5 minutes).
    pub attestation_ttl_seconds: u64,

    // --- Observability ---
    /// The OTLP endpoint for trace and metric export.
    pub otlp_endpoint: String,
    /// The log level (default: "info").
    pub log_level: String,
    /// Sampling rate for verification operations (default: 0.1 / 10%).
    pub verification_sample_rate: f64,

    // --- Feature Flags ---
    /// Enable the SPIRE Agent client adapter.
    pub feature_spire_client: bool,
    /// Enable the PostgreSQL persistence adapter.
    pub feature_postgres_store: bool,
    /// Enable mTLS on the gRPC listener.
    pub feature_mtls: bool,
    /// Enable audit logging for all SVID operations.
    pub feature_audit_log: bool,
}

impl Config {
    /// The environment variable prefix for all config values.
    const ENV_PREFIX: &'static str = "IDENTITY_";

    /// Loads configuration from environment variables.
    pub fn from_env() -> Self {
        Self {
            grpc_bind_addr: env_or("IDENTITY_GRPC_BIND_ADDR", "0.0.0.0:9090"),
            http_bind_addr: env_or("IDENTITY_HTTP_BIND_ADDR", "0.0.0.0:8080"),

            database_url: env_or(
                "IDENTITY_DATABASE_URL",
                "postgres://localhost:5432/identity",
            ),
            database_max_connections: env_or_parse("IDENTITY_DATABASE_MAX_CONNECTIONS", 10),
            database_min_connections: env_or_parse("IDENTITY_DATABASE_MIN_CONNECTIONS", 2),

            spire_agent_socket: env_or(
                "IDENTITY_SPIRE_AGENT_SOCKET",
                "/run/spire/sockets/agent.sock",
            ),
            trust_domain: env_or("IDENTITY_TRUST_DOMAIN", "trust.example.org"),

            max_ttl_seconds: env_or_parse("IDENTITY_MAX_TTL_SECONDS", 259200),
            default_production_ttl: env_or_parse("IDENTITY_DEFAULT_PRODUCTION_TTL", 3600),
            default_staging_ttl: env_or_parse("IDENTITY_DEFAULT_STAGING_TTL", 14400),
            default_development_ttl: env_or_parse("IDENTITY_DEFAULT_DEVELOPMENT_TTL", 86400),
            grace_period_seconds: env_or_parse("IDENTITY_GRACE_PERIOD_SECONDS", 300),
            attestation_ttl_seconds: env_or_parse("IDENTITY_ATTESTATION_TTL_SECONDS", 300),

            otlp_endpoint: env_or("IDENTITY_OTLP_ENDPOINT", "http://localhost:4317"),
            log_level: env_or("IDENTITY_LOG_LEVEL", "info"),
            verification_sample_rate: env_or_parse("IDENTITY_VERIFICATION_SAMPLE_RATE", 0.1),

            feature_spire_client: env_or_parse("IDENTITY_FEATURE_SPIRE_CLIENT", true),
            feature_postgres_store: env_or_parse("IDENTITY_FEATURE_POSTGRES_STORE", true),
            feature_mtls: env_or_parse("IDENTITY_FEATURE_MTLS", false),
            feature_audit_log: env_or_parse("IDENTITY_FEATURE_AUDIT_LOG", true),
        }
    }

    /// Validates the configuration and returns any issues.
    pub fn validate(&self) -> Result<(), Vec<String>> {
        let mut errors = Vec::new();

        if self.grpc_bind_addr.is_empty() {
            errors.push("IDENTITY_GRPC_BIND_ADDR cannot be empty".to_string());
        }

        if self.database_url.is_empty() && self.feature_postgres_store {
            errors.push(
                "IDENTITY_DATABASE_URL cannot be empty when postgres store is enabled".to_string(),
            );
        }

        if self.trust_domain.is_empty() {
            errors.push("IDENTITY_TRUST_DOMAIN cannot be empty".to_string());
        }

        if self.max_ttl_seconds == 0 {
            errors.push("IDENTITY_MAX_TTL_SECONDS must be > 0".to_string());
        }

        if self.grace_period_seconds >= self.default_production_ttl {
            errors
                .push("IDENTITY_GRACE_PERIOD_SECONDS must be less than production TTL".to_string());
        }

        if self.verification_sample_rate < 0.0 || self.verification_sample_rate > 1.0 {
            errors
                .push("IDENTITY_VERIFICATION_SAMPLE_RATE must be between 0.0 and 1.0".to_string());
        }

        if errors.is_empty() {
            Ok(())
        } else {
            Err(errors)
        }
    }

    /// Returns a summary of the configuration for logging.
    pub fn summary(&self) -> String {
        format!(
            "Config {{ grpc={}, http={}, trust_domain={}, max_ttl={}s, \
             prod_ttl={}s, staging_ttl={}s, dev_ttl={}s, grace={}s, \
             spire_socket={}, otlp={}, mtls={}, audit={} }}",
            self.grpc_bind_addr,
            self.http_bind_addr,
            self.trust_domain,
            self.max_ttl_seconds,
            self.default_production_ttl,
            self.default_staging_ttl,
            self.default_development_ttl,
            self.grace_period_seconds,
            self.spire_agent_socket,
            self.otlp_endpoint,
            self.feature_mtls,
            self.feature_audit_log,
        )
    }
}

/// Reads an environment variable or returns the default value.
fn env_or(key: &str, default: &str) -> String {
    env::var(key).unwrap_or_else(|_| default.to_string())
}

/// Reads an environment variable and parses it, or returns the default value.
fn env_or_parse<T: std::str::FromStr>(key: &str, default: T) -> T {
    env::var(key)
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(default)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn default_config_is_valid() {
        let config = Config::from_env();
        assert!(config.validate().is_ok());
    }

    #[test]
    fn config_summary_includes_key_fields() {
        let config = Config::from_env();
        let summary = config.summary();
        assert!(summary.contains("trust_domain="));
        assert!(summary.contains("grpc="));
    }
}
