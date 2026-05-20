// Package di provides compile-time dependency injection wiring using
// google.golang.org/wire. The WireInject function is the entry point
// that Wire uses to generate the wire_gen.go file.
package di

import (
	"log/slog"
	"os"
	"time"

	"github.com/rahlplx/polyglot-microservices-platform/services/gateway/adapters/inbound/grpc"
	"github.com/rahlplx/polyglot-microservices-platform/services/gateway/adapters/inbound/rest"
	"github.com/rahlplx/polyglot-microservices-platform/services/gateway/adapters/outbound/discovery"
	"github.com/rahlplx/polyglot-microservices-platform/services/gateway/adapters/outbound/observability"
	"github.com/rahlplx/polyglot-microservices-platform/services/gateway/adapters/outbound/ratelimit"
	"github.com/rahlplx/polyglot-microservices-platform/services/gateway/domain/models"
	"github.com/rahlplx/polyglot-microservices-platform/services/gateway/domain/services"
	"github.com/rahlplx/polyglot-microservices-platform/services/gateway/infrastructure/config"
	"github.com/rahlplx/polyglot-microservices-platform/services/gateway/infrastructure/identity"
	"github.com/rahlplx/polyglot-microservices-platform/services/gateway/infrastructure/server"
)

//go:generate wire

// App holds all initialized application components.
type App struct {
	Config         *config.Config
	RouterService  *services.RouterService
	GRPCHandler    *grpc.Handler
	RESTController *rest.Controller
	Discovery      *discovery.KubernetesDiscovery
	RateLimiter    *ratelimit.RedisRateLimiter
	OTel           *observability.OTelInstrumentation
	SPIFFE         *identity.SPIFFEIdentity
	Server         *server.Server
	Logger         *slog.Logger
}

// InitializeApp creates and wires all application components using
// manual DI (Wire generation would replace this in production).
// This function follows the dependency graph:
//
//	Config → Logger
//	Config → OTel
//	Config → SPIFFE
//	Config+Logger → Discovery, RateLimiter
//	Discovery+RateLimiter+Logger → RouterService
//	RouterService+Logger → GRPCHandler, RESTController
//	Config+GRPCHandler+RESTController+OTel+SPIFFE → Server
func InitializeApp(cfg *config.Config) (*App, error) {
	// Step 1: Create structured logger
	logger := slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{
		Level: slog.LevelInfo,
	}))
	slog.SetDefault(logger)

	logger.Info("initializing gateway application")

	// Step 2: Initialize OpenTelemetry
	otelInst, err := observability.NewOTelInstrumentation(observability.OTelConfig{
		ServiceName:    cfg.OTel.ServiceName,
		ServiceVersion: cfg.OTel.ServiceVersion,
		OTLPEndpoint:   cfg.OTel.Endpoint,
		TraceEnabled:   cfg.OTel.TraceEnabled,
		MetricsEnabled: cfg.OTel.MetricsEnabled,
		SampleRate:     cfg.OTel.SampleRate,
		ExportInterval: cfg.OTel.ExportInterval,
		ExportTimeout:  cfg.OTel.ExportTimeout,
	}, logger)
	if err != nil {
		return nil, err
	}

	// Step 3: Initialize SPIFFE identity
	spiffeIdentity, err := identity.NewSPIFFEIdentity(identity.SPIFFEConfig{
		Enabled:         cfg.SPIFFE.Enabled,
		TrustDomain:     cfg.SPIFFE.TrustDomain,
		WorkloadAPIAddr: cfg.SPIFFE.WorkloadAPIAddr,
		SVIDTTL:         cfg.SPIFFE.SVIDTTL,
	}, logger)
	if err != nil {
		return nil, err
	}

	// Step 4: Initialize service discovery
	disc, err := discovery.NewKubernetesDiscovery(discovery.KubernetesConfig{
		Namespace:      cfg.Kubernetes.Namespace,
		ResyncInterval: cfg.Kubernetes.ResyncInterval,
		LabelSelector:  cfg.Kubernetes.LabelSelector,
		InCluster:      cfg.Kubernetes.InCluster,
		KubeconfigPath: cfg.Kubernetes.KubeconfigPath,
	}, logger)
	if err != nil {
		return nil, err
	}

	// Step 5: Initialize rate limiter
	rl, err := ratelimit.NewRedisRateLimiter(ratelimit.RedisConfig{
		Addr:         cfg.Redis.Addr,
		Password:     cfg.Redis.Password,
		DB:           cfg.Redis.DB,
		PoolSize:     cfg.Redis.PoolSize,
		MinIdleConns: cfg.Redis.MinIdleConns,
		DialTimeout:  cfg.Redis.DialTimeout,
		ReadTimeout:  cfg.Redis.ReadTimeout,
		WriteTimeout: cfg.Redis.WriteTimeout,
		KeyPrefix:    cfg.Redis.KeyPrefix,
	}, logger)
	if err != nil {
		return nil, err
	}

	// Step 6: Convert config routes/policies to domain models
	routes := configToDomainRoutes(cfg)
	policies := configToDomainPolicies(cfg)

	// Step 7: Create RouterService (domain core)
	routerService := services.NewRouterService(disc, rl, routes, policies, logger)

	// Step 8: Create inbound adapters
	grpcHandler := grpc.NewHandler(routerService, routerService, routerService, routerService, logger)
	restController := rest.NewController(routerService, routerService, routerService, routerService, logger)

	// Step 9: Create server
	srv, err := server.NewServer(server.ServerConfig{
		HTTPPort:        cfg.Server.HTTPPort,
		GRPCPort:        cfg.Server.GRPCPort,
		ReadTimeout:     cfg.Server.ReadTimeout,
		WriteTimeout:    cfg.Server.WriteTimeout,
		IdleTimeout:     cfg.Server.IdleTimeout,
		ShutdownTimeout: cfg.Server.ShutdownTimeout,
	}, grpcHandler, restController, otelInst, spiffeIdentity, logger)
	if err != nil {
		return nil, err
	}

	cfg.LogConfig(logger)

	return &App{
		Config:         cfg,
		RouterService:  routerService,
		GRPCHandler:    grpcHandler,
		RESTController: restController,
		Discovery:      disc,
		RateLimiter:    rl,
		OTel:           otelInst,
		SPIFFE:         spiffeIdentity,
		Server:         srv,
		Logger:         logger,
	}, nil
}

// configToDomainRoutes converts config route definitions to domain models.
func configToDomainRoutes(cfg *config.Config) map[string]models.Route {
	routes := make(map[string]models.Route, len(cfg.Routes))
	for id, rc := range cfg.Routes {
		routes[id] = models.Route{
			ID:              rc.ID,
			Pattern:         rc.Pattern,
			Methods:         rc.Methods,
			UpstreamService: rc.UpstreamService,
			UpstreamPath:    rc.UpstreamPath,
			Timeout:         rc.Timeout,
			RetryCount:      rc.RetryCount,
			RateLimitPolicy: rc.RateLimitPolicy,
			RequireAuth:     rc.RequireAuth,
			Middleware:      rc.Middleware,
			Metadata:        make(map[string]string),
			CreatedAt:       timeNow(),
			UpdatedAt:       timeNow(),
		}
	}
	return routes
}

// configToDomainPolicies converts config policy definitions to domain models.
func configToDomainPolicies(cfg *config.Config) map[string]models.RateLimitPolicy {
	policies := make(map[string]models.RateLimitPolicy, len(cfg.RateLimitPolicies))
	for name, pc := range cfg.RateLimitPolicies {
		policies[name] = models.RateLimitPolicy{
			Name:           name,
			RequestsPerSec: pc.RequestsPerSec,
			BurstSize:      pc.BurstSize,
			Window:         pc.Window,
			KeyTemplate:    pc.KeyTemplate,
		}
	}
	return policies
}

// timeNow returns the current UTC time. Can be overridden in tests for fixed time.
var timeNow = func() time.Time { return time.Now().UTC() }

// WireInject is the Wire provider set. In production, `wire` tool would
// generate wire_gen.go from this. For this implementation, InitializeApp
// provides manual DI with the same dependency graph.
//
// Example wire_gen.go would contain:
//
//      func InitializeApp(cfg *config.Config) (*App, error) {
//          logger := provideLogger()
//          otel := provideOTel(cfg, logger)
//          spiffe := provideSPIFFE(cfg, logger)
//          discovery := provideDiscovery(cfg, logger)
//          ratelimiter := provideRateLimiter(cfg, logger)
//          router := provideRouterService(discovery, ratelimiter, cfg, logger)
//          grpcHandler := provideGRPCHandler(router, logger)
//          restController := provideRESTController(router, logger)
//          srv := provideServer(cfg, grpcHandler, restController, otel, spiffe, logger)
//          return &App{...}, nil
//      }
