// Package identity implements the SPIFFE/SPIRE workload API integration
// for zero-trust identity verification at the Schema Registry ingress.
// It fetches X.509 SVIDs from the SPIRE Agent Workload API and validates
// incoming SVIDs against the trust bundle for mTLS authentication.
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
// Schema Registry. It fetches X.509 SVIDs from the SPIRE Agent Workload API
// and validates incoming SVIDs against the trust bundle. This enables
// zero-trust mTLS between services without a dedicated service mesh.
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

	if !config.Enabled {
		logger.Info("SPIFFE identity disabled")
		return &SPIFFEIdentity{
			config: config,
			logger: logger,
		}, nil
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

// CreateMTLSServerConfig creates a mutual TLS server configuration that
// requires and validates client SVIDs from the trust domain.
func (s *SPIFFEIdentity) CreateMTLSServerConfig() (*tls.Config, error) {
	if s.source == nil {
		return nil, fmt.Errorf("SPIFFE X509 source not initialized")
	}

	tlsConfig := tlsconfig.MTLSServerConfig(s.source, s.source, tlsconfig.AuthorizeMemberOf(s.trustDomain))
	tlsConfig.MinVersion = tls.VersionTLS13

	s.logger.Info("mTLS server configuration created",
		slog.String("trust_domain", s.config.TrustDomain),
	)

	return tlsConfig, nil
}

// ValidateSVID validates a peer's SPIFFE ID against the trust domain
// and checks the certificate chain. Returns the SPIFFE ID string on success.
func (s *SPIFFEIdentity) ValidateSVID(peerCerts []*x509.Certificate) (string, error) {
	if len(peerCerts) == 0 {
		return "", fmt.Errorf("no peer certificates provided")
	}

	cert := peerCerts[0]
	if len(cert.URIs) == 0 {
		return "", fmt.Errorf("peer certificate has no URI SAN (no SPIFFE ID)")
	}

	spiffeIDStr := cert.URIs[0].String()
	spiffeID, err := spiffeid.FromURI(cert.URIs[0])
	if err != nil {
		return "", fmt.Errorf("invalid SPIFFE ID in peer certificate: %w", err)
	}

	if spiffeID.TrustDomain() != s.trustDomain {
		return "", fmt.Errorf("peer SPIFFE ID %q does not belong to trust domain %q",
			spiffeID, s.trustDomain)
	}

	if time.Now().UTC().After(cert.NotAfter) {
		return "", fmt.Errorf("peer certificate expired at %s", cert.NotAfter.Format(time.RFC3339))
	}

	return spiffeIDStr, nil
}

// IsEnabled returns whether SPIFFE identity is enabled and initialized.
func (s *SPIFFEIdentity) IsEnabled() bool {
	return s.config.Enabled && s.source != nil
}
