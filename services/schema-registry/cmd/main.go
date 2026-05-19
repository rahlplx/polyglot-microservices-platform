// Package main is the entry point for the Schema Registry service.
// It initializes configuration, dependency injection, and starts
// the combined gRPC + HTTP server. The Schema Registry provides schema
// registration, validation, compatibility checking, and breaking change
// detection for the polyglot microservices architecture.
package main

import (
	"context"
	"fmt"
	"log/slog"
	"os"
	"os/signal"
	"syscall"

	"github.com/gstack/schema-registry-service/infrastructure/config"
	"github.com/gstack/schema-registry-service/infrastructure/di"
)

// Build-time variables injected via ldflags.
var (
	version   = "0.1.0"
	commitSha = "unknown"
	buildDate = "unknown"
)

func main() {
	if err := run(); err != nil {
		fmt.Fprintf(os.Stderr, "schema-registry service failed: %v\n", err)
		os.Exit(1)
	}
}

func run() error {
	// Load configuration from environment variables
	cfg, err := config.Load()
	if err != nil {
		return fmt.Errorf("failed to load configuration: %w", err)
	}

	// Initialize all application components via DI
	app, err := di.InitializeApp(cfg)
	if err != nil {
		return fmt.Errorf("failed to initialize application: %w", err)
	}

	// Set up graceful shutdown
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()

	// Start SPIFFE identity if enabled
	if cfg.SPIFFE.Enabled {
		if err := app.SPIFFE.Start(ctx); err != nil {
			app.Logger.Warn("SPIFFE identity failed to start, continuing without mTLS",
				slog.String("error", err.Error()),
			)
		} else {
			defer app.SPIFFE.Stop()
		}
	}

	// Verify PostgreSQL connectivity (non-fatal)
	if err := app.SchemaStore.Ping(ctx); err != nil {
		app.Logger.Warn("PostgreSQL ping failed, using in-memory store",
			slog.String("error", err.Error()),
		)
	}

	app.Logger.Info("schema-registry service starting",
		slog.Int("http_port", cfg.Server.HTTPPort),
		slog.Int("grpc_port", cfg.Server.GRPCPort),
		slog.String("version", version),
		slog.String("commit_sha", commitSha),
		slog.String("build_date", buildDate),
		slog.Bool("spiffe_enabled", cfg.SPIFFE.Enabled),
		slog.Bool("otel_enabled", cfg.OTel.Enabled),
		slog.Bool("buf_compilation_enabled", cfg.Features.EnableBufCompilation),
		slog.Bool("breaking_checks_enabled", cfg.Features.EnableBreakingChecks),
	)

	// Start the server (blocks until shutdown)
	if err := app.Server.Start(ctx); err != nil {
		return fmt.Errorf("server error: %w", err)
	}

	// Shutdown OTel
	if err := app.OTel.Shutdown(context.Background()); err != nil {
		app.Logger.Warn("OTel shutdown error",
			slog.String("error", err.Error()),
		)
	}

	// Close schema store
	if err := app.SchemaStore.Close(); err != nil {
		app.Logger.Warn("schema store close error",
			slog.String("error", err.Error()),
		)
	}

	app.Logger.Info("schema-registry service stopped")
	return nil
}
