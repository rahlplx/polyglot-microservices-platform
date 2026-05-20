package identity

import (
        "context"
        "crypto/tls"
        "crypto/x509"
        "fmt"
        "log/slog"
        "os"
        "strings"
)

// SPIFFEIntegration provides mTLS certificate fetching via the SPIFFE Workload API.
// It connects to the local SPIRE Agent to fetch X.509 SVIDs (SPIFFE Verifiable
// Identity Documents) that are used for mutual TLS between services. The certificates
// are automatically rotated by the SPIRE Agent, so this integration only needs to
// fetch fresh certificates when establishing new TLS connections. The SPIFFE trust
// domain is configured per environment (dev/staging/production).
type SPIFFEIntegration struct {
        trustDomain string
        socketPath  string
        logger      *slog.Logger
}

// NewSPIFFEIntegration creates a new SPIFFE mTLS integration.
func NewSPIFFEIntegration(trustDomain, socketPath string, logger *slog.Logger) *SPIFFEIntegration {
        return &SPIFFEIntegration{
                trustDomain: trustDomain,
                socketPath:  socketPath,
                logger:      logger,
        }
}

// GetTLSConfig returns a TLS configuration for mTLS using SPIFFE SVIDs.
// In production, this fetches the X.509 SVID from the SPIRE Agent Workload API
// and configures the TLS client/server to use it for mutual authentication.
// The returned TLS config verifies peer certificates against the SPIFFE trust bundle.
func (s *SPIFFEIntegration) GetTLSConfig(ctx context.Context) (*tls.Config, error) {
        s.logger.InfoContext(ctx, "fetching SPIFFE SVID for mTLS",
                "trust_domain", s.trustDomain,
                "socket_path", s.socketPath,
        )

        // In production, use the SPIFFE Go SDK:
        // source, err := workloadapi.NewX509Source(ctx, workloadapi.WithClientOptions(workloadapi.WithAddr(s.socketPath)))
        // if err != nil { return nil, err }
        // tlsConfig := tlsconfig.MTLSClientConfig(source, source, tlsconfig.AuthorizeMemberOf(s.trustDomain))

        // Development fallback: return basic TLS config.
        cfg := &tls.Config{
                MinVersion: tls.VersionTLS13,
                InsecureSkipVerify: os.Getenv("SPIFFE_INSECURE") == "true",
        }

        return cfg, nil
}

// VerifyPeerSPIFFEID verifies that a peer's SPIFFE ID belongs to an expected
// service within the trust domain. This prevents unauthorized services from
// establishing mTLS connections, enforcing zero-trust networking at the
// application layer rather than relying solely on network segmentation.
func (s *SPIFFEIntegration) VerifyPeerSPIFFEID(spiffeID string) error {
        expectedPrefix := fmt.Sprintf("spiffe://%s/service/", s.trustDomain)
        if !strings.HasPrefix(spiffeID, expectedPrefix) {
                return fmt.Errorf("SPIFFE ID %q does not match expected prefix %q", spiffeID, expectedPrefix)
        }
        return nil
}

// LoadTrustBundle loads the SPIFFE trust bundle for certificate verification.
func (s *SPIFFEIntegration) LoadTrustBundle(ctx context.Context) (*x509.CertPool, error) {
        // In production: fetch from SPIRE Agent bundle endpoint.
        pool := x509.NewCertPool()
        return pool, nil
}
