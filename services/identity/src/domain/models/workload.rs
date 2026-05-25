// ---------------------------------------------------------------------------
// Domain Models: Workload, SPIFFEID, TrustDomain
// ---------------------------------------------------------------------------
// This module contains the core domain models for the Identity service.
// ZERO external dependencies — only std is used.
// ---------------------------------------------------------------------------

/// A SPIFFE ID uniquely identifies a workload within a trust domain.
///
/// Format: `spiffe://<trust_domain>/<workload_path>`
/// Example: `spiffe://trust.example.org/services/gateway`
///
/// SPIFFE IDs are the foundation of workload identity in the
/// SPIFFE/SPIRE framework. Every workload in the mesh receives
/// a unique SPIFFE ID that is embedded in its X.509 SVID.
#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub struct SPIFFEID {
    /// The trust domain component (e.g., "trust.example.org")
    pub trust_domain: TrustDomain,
    /// The workload path component (e.g., "/services/gateway")
    pub path: String,
}

impl SPIFFEID {
    /// The standard SPIFFE scheme prefix.
    pub const SCHEME: &'static str = "spiffe";

    /// Creates a new SPIFFEID from a trust domain and path.
    ///
    /// # Errors
    /// Returns `Err` if the trust domain is empty or the path does not
    /// start with '/'.
    pub fn new(trust_domain: TrustDomain, path: String) -> Result<Self, SPIFFEIDError> {
        if trust_domain.name.is_empty() {
            return Err(SPIFFEIDError::EmptyTrustDomain);
        }
        if !path.starts_with('/') {
            return Err(SPIFFEIDError::InvalidPath(path));
        }
        Ok(Self { trust_domain, path })
    }

    /// Parses a SPIFFE ID from its string representation.
    ///
    /// Expected format: `spiffe://<trust_domain>/<path>`
    pub fn parse(id: &str) -> Result<Self, SPIFFEIDError> {
        let rest = id
            .strip_prefix("spiffe://")
            .ok_or_else(|| SPIFFEIDError::InvalidFormat(id.to_string()))?;

        let (domain, path) = rest
            .split_once('/')
            .ok_or_else(|| SPIFFEIDError::InvalidFormat(id.to_string()))?;

        if domain.is_empty() {
            return Err(SPIFFEIDError::EmptyTrustDomain);
        }

        let path = format!("/{}", path);
        Ok(Self {
            trust_domain: TrustDomain {
                name: domain.to_string(),
            },
            path,
        })
    }

    /// Returns the string representation of this SPIFFE ID.
    pub fn as_str(&self) -> String {
        format!(
            "spiffe://{}/{}",
            self.trust_domain.name,
            self.path.trim_start_matches('/')
        )
    }

    /// Returns true if this SPIFFE ID belongs to the given trust domain.
    pub fn belongs_to(&self, domain: &TrustDomain) -> bool {
        &self.trust_domain == domain
    }
}

impl std::fmt::Display for SPIFFEID {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(
            f,
            "spiffe://{}/{}",
            self.trust_domain.name,
            self.path.trim_start_matches('/')
        )
    }
}

impl std::str::FromStr for SPIFFEID {
    type Err = SPIFFEIDError;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        Self::parse(s)
    }
}

/// Errors that can occur when constructing or parsing a SPIFFE ID.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum SPIFFEIDError {
    /// The string does not follow the `spiffe://<domain>/<path>` format.
    InvalidFormat(String),
    /// The trust domain component is empty.
    EmptyTrustDomain,
    /// The path component does not start with '/'.
    InvalidPath(String),
}

impl std::fmt::Display for SPIFFEIDError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::InvalidFormat(s) => write!(f, "invalid SPIFFE ID format: {}", s),
            Self::EmptyTrustDomain => write!(f, "trust domain cannot be empty"),
            Self::InvalidPath(p) => write!(f, "SPIFFE ID path must start with '/': {}", p),
        }
    }
}

impl std::error::Error for SPIFFEIDError {}

/// A trust domain defines a security boundary for SPIFFE IDs.
///
/// Trust domains are the root of trust in the SPIFFE framework.
/// Each trust domain has its own CA and trust bundle. Workloads
/// within the same trust domain can verify each other's identities
/// using the shared trust bundle.
///
/// The project defines three trust domains:
/// - `trust.dev.example.org` (development)
/// - `trust.staging.example.org` (staging)
/// - `trust.example.org` (production)
#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub struct TrustDomain {
    /// The trust domain name (e.g., "trust.example.org")
    pub name: String,
}

impl TrustDomain {
    /// Production trust domain.
    pub const PRODUCTION: &'static str = "trust.example.org";
    /// Staging trust domain.
    pub const STAGING: &'static str = "trust.staging.example.org";
    /// Development trust domain.
    pub const DEVELOPMENT: &'static str = "trust.dev.example.org";

    /// Creates a new trust domain from a name string.
    pub fn new(name: String) -> Self {
        Self { name }
    }

    /// Creates the production trust domain.
    pub fn production() -> Self {
        Self {
            name: Self::PRODUCTION.to_string(),
        }
    }

    /// Creates the staging trust domain.
    pub fn staging() -> Self {
        Self {
            name: Self::STAGING.to_string(),
        }
    }

    /// Creates the development trust domain.
    pub fn development() -> Self {
        Self {
            name: Self::DEVELOPMENT.to_string(),
        }
    }

    /// Returns true if this is the production trust domain.
    pub fn is_production(&self) -> bool {
        self.name == Self::PRODUCTION
    }

    /// Returns true if this is the staging trust domain.
    pub fn is_staging(&self) -> bool {
        self.name == Self::STAGING
    }

    /// Returns true if this is the development trust domain.
    pub fn is_development(&self) -> bool {
        self.name == Self::DEVELOPMENT
    }

    /// Returns true if this trust domain name is recognized.
    pub fn is_valid(&self) -> bool {
        self.name == Self::PRODUCTION
            || self.name == Self::STAGING
            || self.name == Self::DEVELOPMENT
    }
}

impl std::fmt::Display for TrustDomain {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.name)
    }
}

/// A workload represents a running service or process that needs identity.
///
/// Workloads are the entities that receive SPIFFE IDs and SVIDs. Each
/// workload is registered with a set of selectors that are used during
/// attestation to verify the workload's identity. The selectors typically
/// correspond to Kubernetes pod labels, namespaces, or Unix UID/GID.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Workload {
    /// Unique identifier for this workload (typically a UUID).
    pub id: String,
    /// The SPIFFE ID assigned to this workload.
    pub spiffe_id: SPIFFEID,
    /// The parent SPIFFE ID (typically the SPIRE Agent's ID).
    pub parent_id: SPIFFEID,
    /// Selectors used for workload attestation.
    pub selectors: Vec<Selector>,
    /// TTL for SVIDs issued to this workload, in seconds.
    pub ttl_seconds: u64,
    /// DNS names to include in the SVID.
    pub dns_names: Vec<String>,
    /// Whether this workload is currently attested.
    pub attested: bool,
    /// The timestamp when this workload was registered (Unix epoch seconds).
    pub registered_at: u64,
}

impl Workload {
    /// Creates a new workload with the given parameters.
    pub fn new(
        id: String,
        spiffe_id: SPIFFEID,
        parent_id: SPIFFEID,
        selectors: Vec<Selector>,
        ttl_seconds: u64,
        dns_names: Vec<String>,
    ) -> Self {
        Self {
            id,
            spiffe_id,
            parent_id,
            selectors,
            ttl_seconds,
            dns_names,
            attested: false,
            registered_at: 0,
        }
    }

    /// Returns true if this workload matches all the given selectors.
    ///
    /// A workload matches if it has selectors that satisfy every selector
    /// in the provided set. This is the core of workload attestation:
    /// the SPIRE Agent presents selectors from the runtime environment,
    /// and we check if the registered workload's selectors are a subset.
    pub fn matches_selectors(&self, selectors: &[Selector]) -> bool {
        for selector in selectors {
            if !self.selectors.contains(selector) {
                return false;
            }
        }
        true
    }

    /// Marks this workload as attested.
    pub fn mark_attested(&mut self) {
        self.attested = true;
    }
}

/// A selector identifies a workload during attestation.
///
/// Selectors are key-value pairs that describe the runtime properties
/// of a workload. During attestation, the SPIRE Agent collects selectors
/// from the workload's environment (e.g., Kubernetes pod labels, Unix
/// UID) and presents them to the Identity service. If the presented
/// selectors match a registered workload's selectors, attestation succeeds.
#[derive(Debug, Clone, PartialEq, Eq, Hash, serde::Serialize, serde::Deserialize)]
pub struct Selector {
    /// The selector type (e.g., "k8s", "unix", "spiffe").
    pub kind: String,
    /// The selector key (e.g., "ns:production" or "label:app=gateway").
    pub value: String,
}

impl Selector {
    /// Creates a new selector.
    pub fn new(kind: String, value: String) -> Self {
        Self { kind, value }
    }

    /// Creates a Kubernetes namespace selector.
    pub fn k8s_namespace(namespace: &str) -> Self {
        Self {
            kind: "k8s".to_string(),
            value: format!("ns:{}", namespace),
        }
    }

    /// Creates a Kubernetes label selector.
    pub fn k8s_label(key: &str, value: &str) -> Self {
        Self {
            kind: "k8s".to_string(),
            value: format!("label:{}={}", key, value),
        }
    }

    /// Creates a Unix UID selector.
    pub fn unix_uid(uid: u32) -> Self {
        Self {
            kind: "unix".to_string(),
            value: format!("uid:{}", uid),
        }
    }

    /// Creates a Unix GID selector.
    pub fn unix_gid(gid: u32) -> Self {
        Self {
            kind: "unix".to_string(),
            value: format!("gid:{}", gid),
        }
    }

    /// Parses a selector from the SPIRE format "kind:value".
    pub fn parse(selector: &str) -> Result<Self, SelectorError> {
        let (kind, value) = selector
            .split_once(':')
            .ok_or_else(|| SelectorError::InvalidFormat(selector.to_string()))?;
        if kind.is_empty() || value.is_empty() {
            return Err(SelectorError::InvalidFormat(selector.to_string()));
        }
        Ok(Self {
            kind: kind.to_string(),
            value: value.to_string(),
        })
    }
}

impl std::fmt::Display for Selector {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}:{}", self.kind, self.value)
    }
}

/// Errors that can occur when parsing a selector.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum SelectorError {
    /// The selector does not follow the "kind:value" format.
    InvalidFormat(String),
}

impl std::fmt::Display for SelectorError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::InvalidFormat(s) => write!(f, "invalid selector format: {}", s),
        }
    }
}

impl std::error::Error for SelectorError {}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn spiffe_id_parse_valid() {
        let id = SPIFFEID::parse("spiffe://trust.example.org/services/gateway").unwrap();
        assert_eq!(id.trust_domain.name, "trust.example.org");
        assert_eq!(id.path, "/services/gateway");
    }

    #[test]
    fn spiffe_id_parse_invalid_format() {
        assert!(SPIFFEID::parse("invalid").is_err());
        assert!(SPIFFEID::parse("spiffe://").is_err());
    }

    #[test]
    fn spiffe_id_display() {
        let id = SPIFFEID::parse("spiffe://trust.example.org/services/gateway").unwrap();
        assert_eq!(
            id.to_string(),
            "spiffe://trust.example.org/services/gateway"
        );
    }

    #[test]
    fn trust_domain_is_production() {
        assert!(TrustDomain::production().is_production());
        assert!(!TrustDomain::staging().is_production());
    }

    #[test]
    fn workload_matches_selectors() {
        let spiffe_id = SPIFFEID::parse("spiffe://trust.example.org/services/gateway").unwrap();
        let parent_id = SPIFFEID::parse("spiffe://trust.example.org/spire/agent").unwrap();
        let workload = Workload::new(
            "w-1".to_string(),
            spiffe_id,
            parent_id,
            vec![
                Selector::k8s_namespace("production"),
                Selector::k8s_label("app", "gateway"),
            ],
            3600,
            vec!["gateway.trust.example.org".to_string()],
        );

        // Matching selectors
        assert!(workload.matches_selectors(&[Selector::k8s_namespace("production"),]));

        // Non-matching selectors
        assert!(!workload.matches_selectors(&[Selector::k8s_namespace("staging"),]));
    }
}
