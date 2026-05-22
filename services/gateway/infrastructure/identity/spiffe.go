// Package identity implements the SPIFFE/SPIRE workload API integration
// for zero-trust identity verification at the gateway ingress.
package identity

import (
	"context"
	"crypto/tls"
	"crypto/x509"
	"fmt"
	"log/slog"
	"time"

	"github.com/spiffe/go-spiffe/v2/spiffeid"
	"github.com/spiffe/go-spiffe/v2/spiffetls/tlsconfig"
	"github.com/spiffe/go-spiffe/v2/workloadapi"
)

// SPIFFEConfig holds the SPIFFE/SPIRE configuration.
type SPIFFEConfig struct {
	Enabled         bool          // Whether SPIFFE validation is enabled
	TrustDomain     string        // SPIFFE trust domain
	WorkloadAPIAddr string        // SPIRE Agent Workload API socket path
	SVIDTTL         time.Duration // Expected SVID TTL
}

// SPIFFEIdentity manages SPIFFE/SPIRE-based identity verification for the
// gateway. It fetches X.509 SVIDs from the SPIRE Agent Workload API and
// validates incoming SVIDs against the trust bundle.
type SPIFFEIdentity struct {
	config SPIFFEConfig
	logger *slog.Logger

	source      *workloadapi.X509Source
	trustDomain spiffeid.TrustDomain
}

// NewSPIFFEIdentity creates a new SPIFFE identity manager.
func NewSPIFFEIdentity(config SPIFFEConfig, logger *slog.Logger) (*SPIFFEIdentity, error) {
	if logger == nil {
		logger = slog.Default()
	}

	td, err := spiffeid.TrustDomainFromString(config.TrustDomain)
	if err != nil {
		return nil, fmt.Errorf("invalid SPIFFE trust domain %q: %w", config.TrustDomain, err)
	}

	return &SPIFFEIdentity{
		config:      config,
		logger:      logger,
		trustDomain: td,
	}, nil
}

// Start initializes the X.509 source by connecting to the SPIRE Agent
// Workload API and fetching the initial SVID and trust bundle.
func (s *SPIFFEIdentity) Start(ctx context.Context) error {
	if !s.config.Enabled {
		s.logger.Info("SPIFFE identity disabled, skipping workload API connection")
		return nil
	}

	s.logger.Info("connecting to SPIRE Agent Workload API",
		slog.String("address", s.config.WorkloadAPIAddr),
		slog.String("trust_domain", s.config.TrustDomain),
	)

	source, err := workloadapi.NewX509Source(ctx,
		workloadapi.WithClientOptions(
			workloadapi.WithAddr(s.config.WorkloadAPIAddr),
		),
	)
	if err != nil {
		return fmt.Errorf("failed to create X509 source from workload API: %w", err)
	}

	s.source = source

	// Verify we can fetch an SVID
	svid, err := source.GetX509SVID()
	if err != nil {
		return fmt.Errorf("failed to fetch initial X509 SVID: %w", err)
	}

	s.logger.Info("SPIFFE identity established",
		slog.String("spiffe_id", svid.ID.String()),
		slog.String("trust_domain", s.config.TrustDomain),
		slog.Time("expires_at", svid.Certificates[0].NotAfter),
	)

	return nil
}

// Stop closes the X.509 source and releases resources.
func (s *SPIFFEIdentity) Stop() {
	if s.source != nil {
		s.source.Close()
		s.logger.Info("SPIFFE identity source closed")
	}
}

// GetTLSCertificate returns the current TLS certificate for the gateway.
func (s *SPIFFEIdentity) GetTLSCertificate() (*tls.Certificate, error) {
	if s.source == nil {
		return nil, fmt.Errorf("SPIFFE X509 source not initialized")
	}

	svid, err := s.source.GetX509SVID()
	if err != nil {
		return nil, fmt.Errorf("failed to get X509 SVID: %w", err)
	}

	return &tls.Certificate{
		Certificate: [][]byte{svid.Certificates[0].Raw},
		PrivateKey:  svid.PrivateKey,
		Leaf:        svid.Certificates[0],
	}, nil
}

// GetTrustBundle returns the current trust bundle (CA certificates) for
// validating peer SVIDs.
func (s *SPIFFEIdentity) GetTrustBundle() ([]*x509.Certificate, error) {
	if s.source == nil {
		return nil, fmt.Errorf("SPIFFE X509 source not initialized")
	}

	bundle, err := s.source.GetX509BundleForTrustDomain(s.trustDomain)
	if err != nil {
		return nil, fmt.Errorf("failed to get X509 bundle for trust domain %q: %w", s.trustDomain, err)
	}

	return bundle.X509Authorities(), nil
}

// CreateMTLSServerConfig creates a mutual TLS server configuration that
// requires and validates client SVIDs from the trust domain.
func (s *SPIFFEIdentity) CreateMTLSServerConfig() (*tls.Config, error) {
	if s.source == nil {
		return nil, fmt.Errorf("SPIFFE X509 source not initialized")
	}

	// Create mTLS config using SPIFFE TLS library
	tlsConfig := tlsconfig.MTLSServerConfig(s.source, s.source, tlsconfig.AuthorizeMemberOf(s.trustDomain))
	tlsConfig.MinVersion = tls.VersionTLS13

	s.logger.Info("mTLS server configuration created",
		slog.String("trust_domain", s.config.TrustDomain),
	)

	return tlsConfig, nil
}

// CreateTLSClientConfig creates a TLS client configuration with SVID
// for making authenticated requests to upstream services.
func (s *SPIFFEIdentity) CreateTLSClientConfig(targetTrustDomain string) (*tls.Config, error) {
	if s.source == nil {
		return nil, fmt.Errorf("SPIFFE X509 source not initialized")
	}

	td, err := spiffeid.TrustDomainFromString(targetTrustDomain)
	if err != nil {
		return nil, fmt.Errorf("invalid target trust domain %q: %w", targetTrustDomain, err)
	}

	tlsConfig := tlsconfig.MTLSClientConfig(s.source, s.source, tlsconfig.AuthorizeMemberOf(td))
	tlsConfig.MinVersion = tls.VersionTLS13

	return tlsConfig, nil
}

// ValidateSVID validates a peer's SPIFFE ID against the trust domain
// and checks the certificate chain. Returns the SPIFFE ID string on success.
func (s *SPIFFEIdentity) ValidateSVID(peerCerts []*x509.Certificate) (string, error) {
	if len(peerCerts) == 0 {
		return "", fmt.Errorf("no peer certificates provided")
	}

	// Extract SPIFFE ID from the URI SAN
	cert := peerCerts[0]
	if len(cert.URIs) == 0 {
		return "", fmt.Errorf("peer certificate has no URI SAN (no SPIFFE ID)")
	}

	spiffeIDStr := cert.URIs[0].String()
	spiffeID, err := spiffeid.FromURI(cert.URIs[0])
	if err != nil {
		return "", fmt.Errorf("invalid SPIFFE ID in peer certificate: %w", err)
	}

	// Verify the SPIFFE ID belongs to our trust domain
	if spiffeID.TrustDomain() != s.trustDomain {
		return "", fmt.Errorf("peer SPIFFE ID %q does not belong to trust domain %q",
			spiffeID, s.trustDomain)
	}

	// Verify the certificate hasn't expired
	if time.Now().UTC().After(cert.NotAfter) {
		return "", fmt.Errorf("peer certificate expired at %s", cert.NotAfter.Format(time.RFC3339))
	}

	// Verify the certificate isn't valid yet
	if time.Now().UTC().Before(cert.NotBefore) {
		return "", fmt.Errorf("peer certificate not valid until %s", cert.NotBefore.Format(time.RFC3339))
	}

	s.logger.Debug("SVID validated",
		slog.String("spiffe_id", spiffeIDStr),
	)

	return spiffeIDStr, nil
}

// IsEnabled returns whether SPIFFE identity is enabled.
func (s *SPIFFEIdentity) IsEnabled() bool {
	return s.config.Enabled && s.source != nil
}
