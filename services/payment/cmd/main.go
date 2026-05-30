// Package main is the entry point for the Payment service.
// It initializes configuration, dependency injection, and starts
// the gRPC server for payment processing.
package main

import (
	"context"
	"log/slog"
	"os"

	"github.com/rahlplx/polyglot-microservices-platform/services/payment/infrastructure/config"
	"github.com/rahlplx/polyglot-microservices-platform/services/payment/infrastructure/di"
	"github.com/rahlplx/polyglot-microservices-platform/services/payment/infrastructure/server"
)

func main() {
	logger := slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{Level: slog.LevelInfo}))

	// Load configuration from environment variables.
	cfg, err := config.Load()
	if err != nil {
		logger.Error("failed to load configuration", "error", err)
		os.Exit(1)
	}

	logger.Info("payment service initializing",
		"grpc_port", cfg.Server.GRPCPort,
		"gateway_provider", cfg.Gateway.Provider,
		"spiffe_enabled", cfg.SPIFFE.Enabled,
	)

	// Wire all dependencies via the DI container.
	_ = di.NewContainer(cfg)

	// Create and start the gRPC server.
	srv := server.NewServer(cfg.Server.GRPCPort, cfg.Server.MetricsPort, logger)

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	if err := srv.Start(ctx); err != nil {
		logger.Error("server failed", "error", err)
		os.Exit(1)
	}
}
