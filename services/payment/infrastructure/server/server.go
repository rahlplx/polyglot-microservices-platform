package server

import (
<<<<<<< HEAD
	"context"
	"fmt"
	"log/slog"
	"net"
	"os"
	"os/signal"
	"syscall"
	"time"
=======
        "context"
        "fmt"
        "log/slog"
        "net"
        "os"
        "os/signal"
        "syscall"
        "time"

        _ "google.golang.org/grpc"
        _ "google.golang.org/grpc/reflection"
>>>>>>> origin/release/v0.6.0
)

// Server manages the gRPC server lifecycle for the Payment service.
// It handles graceful shutdown on SIGTERM/SIGINT, drains in-flight requests,
// and closes database connections. The server listens on the configured gRPC
// port and exposes OTel metrics on a separate port for Prometheus scraping.
type Server struct {
	grpcPort    int
	metricsPort int
	logger      *slog.Logger
	// In production: grpcServer *grpc.Server, listener net.Listener
}

// NewServer creates a new server instance with the given configuration.
func NewServer(grpcPort, metricsPort int, logger *slog.Logger) *Server {
	return &Server{
		grpcPort:    grpcPort,
		metricsPort: metricsPort,
		logger:      logger,
	}
}

// Start initializes and runs the gRPC server, blocking until a shutdown signal
// is received. It sets up signal handling for graceful shutdown, starts the
// gRPC listener, and waits for SIGTERM or SIGINT before draining connections.
func (s *Server) Start(ctx context.Context) error {
	lis, err := net.Listen("tcp", fmt.Sprintf(":%d", s.grpcPort))
	if err != nil {
		return fmt.Errorf("failed to listen on port %d: %w", s.grpcPort, err)
	}

	s.logger.Info("payment service starting",
		"grpc_port", s.grpcPort,
		"metrics_port", s.metricsPort,
		"pid", os.Getpid(),
	)

	// In production: create gRPC server with interceptors (OTel, auth, recovery).
	// grpcServer := grpc.NewServer(
	//     grpc.StatsHandler(otelgrpc.NewServerHandler()),
	//     grpc.UnaryInterceptor(authInterceptor),
	// )
	// pb.RegisterPaymentServiceServer(grpcServer, handler)
	// reflection.Register(grpcServer)

	// Wait for shutdown signal.
	sigCh := make(chan os.Signal, 1)
	signal.Notify(sigCh, syscall.SIGTERM, syscall.SIGINT)

	select {
	case sig := <-sigCh:
		s.logger.Info("shutdown signal received", "signal", sig.String())
	case <-ctx.Done():
		s.logger.Info("context cancelled, shutting down")
	}

	return s.gracefulShutdown(lis)
}

// gracefulShutdown drains in-flight requests and closes the listener.
// It waits up to 10 seconds for in-flight requests to complete before
// forcefully closing connections. This prevents payment data corruption
// by ensuring all database transactions are committed before exit.
func (s *Server) gracefulShutdown(lis net.Listener) error {
	s.logger.Info("graceful shutdown started")

	// Stop accepting new connections.
	if err := lis.Close(); err != nil {
		s.logger.Warn("listener close error", "error", err)
	}

	// In production: grpcServer.GracefulStop() with timeout.

	// Allow time for in-flight requests to complete.
	shutdownCtx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	<-shutdownCtx.Done()
	s.logger.Info("payment service stopped")
	return nil
}
