// Package main is the entry point for the Gateway service.
// It initializes configuration, dependency injection, and starts
// the combined gRPC + HTTP server.
package main

import (
        "context"
        "fmt"
        "log/slog"
        "os"
        "os/signal"
        "syscall"

        "github.com/rahlplx/polyglot-microservices-platform/services/gateway/infrastructure/config"
        "github.com/rahlplx/polyglot-microservices-platform/services/gateway/infrastructure/di"
)

func main() {
        if err := run(); err != nil {
                fmt.Fprintf(os.Stderr, "gateway service failed: %v\n", err)
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

        // Start service discovery background sync
        if err := app.Discovery.Start(ctx); err != nil {
                app.Logger.Warn("service discovery failed to start, using cached endpoints",
                        slog.String("error", err.Error()),
                )
        } else {
                defer app.Discovery.Stop()
        }

        // Verify Redis connectivity (non-fatal)
        if err := app.RateLimiter.Ping(ctx); err != nil {
                app.Logger.Warn("Redis ping failed, rate limiting may be unavailable",
                        slog.String("error", err.Error()),
                )
        }

	app.Logger.Info("gateway service starting",
		slog.Int("http_port", cfg.Server.HTTPPort),
		slog.Int("grpc_port", cfg.Server.GRPCPort),
		slog.Bool("spiffe_enabled", cfg.SPIFFE.Enabled),
		slog.Bool("otel_enabled", cfg.OTel.Enabled),
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

        app.Logger.Info("gateway service stopped")
        return nil
}
