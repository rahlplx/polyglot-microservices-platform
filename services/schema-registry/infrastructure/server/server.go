// Package server manages the dual gRPC and HTTP server lifecycle for the
// Schema Registry. It handles graceful startup and shutdown, health endpoints,
// middleware configuration, and the integration of gRPC-gateway for REST-to-gRPC
// transcoding on the same HTTP port.
package server

import (
        "context"
        "fmt"
        "log/slog"
        "net"
        "net/http"
        "time"

        "google.golang.org/grpc"
        "google.golang.org/grpc/credentials"
        "google.golang.org/grpc/keepalive"
        "google.golang.org/grpc/reflection"

        grpcHandler "github.com/rahlplx/polyglot-microservices-platform/services/schema-registry/adapters/inbound/grpc"
        restController "github.com/rahlplx/polyglot-microservices-platform/services/schema-registry/adapters/inbound/rest"
        "github.com/rahlplx/polyglot-microservices-platform/services/schema-registry/adapters/outbound/observability"
        "github.com/rahlplx/polyglot-microservices-platform/services/schema-registry/infrastructure/identity"

        "go.opentelemetry.io/contrib/instrumentation/google.golang.org/grpc/otelgrpc"
        "go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp"
)

// ServerConfig holds the server configuration.
type ServerConfig struct {
        HTTPPort        int
        GRPCPort        int
        ReadTimeout     time.Duration
        WriteTimeout    time.Duration
        IdleTimeout     time.Duration
        ShutdownTimeout time.Duration
}

// Server manages the combined gRPC and HTTP server lifecycle for the
// Schema Registry. The gRPC server handles RPC calls from other services
// within the mesh, while the HTTP server exposes the REST API for external
// clients and the Confluent-compatible Schema Registry interface.
type Server struct {
        config      ServerConfig
        grpcHandler *grpcHandler.Handler
        restCtrl    *restController.Controller
        otel        *observability.OTelInstrumentation
        spiffe      *identity.SPIFFEIdentity
        logger      *slog.Logger

        grpcServer *grpc.Server
        httpServer *http.Server
}

// NewServer creates a new Server with the given dependencies.
func NewServer(
        config ServerConfig,
        grpcH *grpcHandler.Handler,
        restCtrl *restController.Controller,
        otel *observability.OTelInstrumentation,
        spiffe *identity.SPIFFEIdentity,
        logger *slog.Logger,
) (*Server, error) {
        if logger == nil {
                logger = slog.Default()
        }

        s := &Server{
                config:      config,
                grpcHandler: grpcH,
                restCtrl:    restCtrl,
                otel:        otel,
                spiffe:      spiffe,
                logger:      logger,
        }

        if err := s.buildGRPCServer(); err != nil {
                return nil, fmt.Errorf("failed to build gRPC server: %w", err)
        }

        s.buildHTTPServer()

        return s, nil
}

// buildGRPCServer creates and configures the gRPC server with interceptors
// for OTel tracing, authentication, and request size limits.
func (s *Server) buildGRPCServer() error {
        opts := []grpc.ServerOption{
                grpc.KeepaliveParams(keepalive.ServerParameters{
                        MaxConnectionIdle:     5 * time.Minute,
                        MaxConnectionAge:      30 * time.Minute,
                        MaxConnectionAgeGrace: 10 * time.Second,
                        Time:                  30 * time.Second,
                        Timeout:               10 * time.Second,
                }),
                grpc.KeepaliveEnforcementPolicy(keepalive.EnforcementPolicy{
                        MinTime:             10 * time.Second,
                        PermitWithoutStream: true,
                }),
                grpc.MaxRecvMsgSize(5 * 1024 * 1024), // 5MB per schema definition
                grpc.MaxSendMsgSize(5 * 1024 * 1024),
        }

        // Add OTel interceptor if available
        if s.otel != nil && s.otel.TracerProvider() != nil {
                opts = append(opts,
                        grpc.StatsHandler(otelgrpc.NewServerHandler()),
                )
        }

        // Add mTLS if SPIFFE is enabled
        if s.spiffe != nil && s.spiffe.IsEnabled() {
                tlsConfig, err := s.spiffe.CreateMTLSServerConfig()
                if err != nil {
                        s.logger.Warn("failed to create mTLS config, falling back to non-TLS gRPC",
                                slog.String("error", err.Error()),
                        )
                } else {
                        opts = append(opts, grpc.Creds(credentials.NewTLS(tlsConfig)))
                        s.logger.Info("gRPC server configured with SPIFFE mTLS")
                }
        }

        s.grpcServer = grpc.NewServer(opts...)
        s.grpcHandler.RegisterServer(s.grpcServer)
        reflection.Register(s.grpcServer)

        return nil
}

// buildHTTPServer creates and configures the HTTP server with middleware
// for OTel tracing, CORS, recovery, and logging.
func (s *Server) buildHTTPServer() {
        handler := s.restCtrl.Handler()

        // Add OTel HTTP instrumentation
        if s.otel != nil {
                handler = otelhttp.NewHandler(handler, "schema-registry.http")
        }

        // Add CORS middleware
        handler = restController.CORSMiddleware(nil)(handler)

        // Add recovery middleware
        handler = restController.RecoveryMiddleware(s.logger)(handler)

        // Add logging middleware (outermost)
        handler = restController.LoggingMiddleware(s.logger)(handler)

        s.httpServer = &http.Server{
                Addr:         fmt.Sprintf(":%d", s.config.HTTPPort),
                Handler:      handler,
                ReadTimeout:  s.config.ReadTimeout,
                WriteTimeout: s.config.WriteTimeout,
                IdleTimeout:  s.config.IdleTimeout,
        }
}

// Start starts both the gRPC and HTTP servers. It blocks until the context
// is cancelled or a server encounters a fatal error.
func (s *Server) Start(ctx context.Context) error {
        errCh := make(chan error, 2)

        // Start gRPC server
        grpcLis, err := net.Listen("tcp", fmt.Sprintf(":%d", s.config.GRPCPort))
        if err != nil {
                return fmt.Errorf("failed to listen on gRPC port %d: %w", s.config.GRPCPort, err)
        }

        go func() {
                s.logger.Info("starting gRPC server",
                        slog.Int("port", s.config.GRPCPort),
                )
                if err := s.grpcServer.Serve(grpcLis); err != nil {
                        errCh <- fmt.Errorf("gRPC server error: %w", err)
                }
        }()

        // Start HTTP server
        go func() {
                s.logger.Info("starting HTTP server",
                        slog.Int("port", s.config.HTTPPort),
                )
                if err := s.httpServer.ListenAndServe(); err != nil && err != http.ErrServerClosed {
                        errCh <- fmt.Errorf("HTTP server error: %w", err)
                }
        }()

        s.logger.Info("schema-registry server started",
                slog.Int("http_port", s.config.HTTPPort),
                slog.Int("grpc_port", s.config.GRPCPort),
        )

        // Wait for context cancellation or server error
        select {
        case <-ctx.Done():
                s.logger.Info("shutdown signal received")
                return s.Shutdown()
        case err := <-errCh:
                return err
        }
}

// Shutdown gracefully stops both servers with a timeout.
func (s *Server) Shutdown() error {
        ctx, cancel := context.WithTimeout(context.Background(), s.config.ShutdownTimeout)
        defer cancel()

        var errs []error

        // Gracefully stop gRPC server
        s.logger.Info("stopping gRPC server...")
        done := make(chan struct{})
        go func() {
                s.grpcServer.GracefulStop()
                close(done)
        }()
        select {
        case <-done:
                s.logger.Info("gRPC server stopped gracefully")
        case <-ctx.Done():
                s.grpcServer.Stop()
                s.logger.Warn("gRPC server forced stop after timeout")
        }

        // Gracefully stop HTTP server
        s.logger.Info("stopping HTTP server...")
        if err := s.httpServer.Shutdown(ctx); err != nil {
                errs = append(errs, fmt.Errorf("HTTP server shutdown error: %w", err))
        } else {
                s.logger.Info("HTTP server stopped gracefully")
        }

        if len(errs) > 0 {
                return fmt.Errorf("shutdown errors: %v", errs)
        }

        return nil
}
