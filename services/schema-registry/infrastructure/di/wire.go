// Package di provides dependency injection wiring for the Schema Registry service.
// It creates and wires all application components following the dependency graph,
// ensuring that each component receives only the ports it depends on, not
// concrete implementations.
package di

import (
	"log/slog"
	"os"

	"github.com/rahlplx/polyglot-microservices-platform/services/schema-registry/adapters/inbound/grpc"
	"github.com/rahlplx/polyglot-microservices-platform/services/schema-registry/adapters/inbound/rest"
	"github.com/rahlplx/polyglot-microservices-platform/services/schema-registry/adapters/outbound/compiler"
	"github.com/rahlplx/polyglot-microservices-platform/services/schema-registry/adapters/outbound/observability"
	"github.com/rahlplx/polyglot-microservices-platform/services/schema-registry/adapters/outbound/persistence"
	"github.com/rahlplx/polyglot-microservices-platform/services/schema-registry/adapters/outbound/validation"
	"github.com/rahlplx/polyglot-microservices-platform/services/schema-registry/domain/services"
	"github.com/rahlplx/polyglot-microservices-platform/services/schema-registry/infrastructure/config"
	"github.com/rahlplx/polyglot-microservices-platform/services/schema-registry/infrastructure/identity"
	"github.com/rahlplx/polyglot-microservices-platform/services/schema-registry/infrastructure/server"
)

//go:generate wire

// App holds all initialized application components.
type App struct {
	Config              *config.Config
	RegistryService     *services.RegistryService
	CompatibilityService *services.CompatibilityService
	ValidationService   *services.ValidationService
	GRPCHandler         *grpc.Handler
	RESTController      *rest.Controller
	SchemaStore         *persistence.PostgresSchemaStore
	BufCompiler         *compiler.BufCompiler
	BufBreakingAdapter  *validation.BufBreakingAdapter
	OTel                *observability.OTelInstrumentation
	SPIFFE              *identity.SPIFFEIdentity
	Server              *server.Server
	Logger              *slog.Logger
}

// InitializeApp creates and wires all application components using manual DI.
// This function follows the dependency graph:
//
//	Config -> Logger
//	Config -> OTel
//	Config -> SPIFFE
//	Config+Logger -> SchemaStore, BufCompiler, BufBreakingAdapter
//	SchemaStore+BufCompiler+BufBreakingAdapter+Logger -> CompatibilityService
//	SchemaStore+BufCompiler+BufBreakingAdapter+CompatibilityService+Logger -> ValidationService
//	SchemaStore+BufCompiler+BufBreakingAdapter+Logger -> RegistryService
//	RegistryService+CompatibilityService+ValidationService+Logger -> GRPCHandler, RESTController
//	Config+GRPCHandler+RESTController+OTel+SPIFFE -> Server
func InitializeApp(cfg *config.Config) (*App, error) {
	// Step 1: Create structured logger
	logger := slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{
		Level: slog.LevelInfo,
	}))
	slog.SetDefault(logger)

	logger.Info("initializing schema-registry application")

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

	// Step 4: Initialize PostgreSQL schema store
	schemaStore, err := persistence.NewPostgresSchemaStore(persistence.PostgresConfig{
		Host:            cfg.Postgres.Host,
		Port:            cfg.Postgres.Port,
		User:            cfg.Postgres.User,
		Password:        cfg.Postgres.Password,
		Database:        cfg.Postgres.Database,
		SSLMode:         cfg.Postgres.SSLMode,
		MaxConns:        cfg.Postgres.MaxConns,
		MinConns:        cfg.Postgres.MinConns,
		MaxConnIdleTime: cfg.Postgres.MaxConnIdleTime,
		MaxConnLifetime: cfg.Postgres.MaxConnLifetime,
	}, logger)
	if err != nil {
		return nil, err
	}

	// Step 5: Initialize Buf compiler (optional)
	var bufCompiler *compiler.BufCompiler
	if cfg.Features.EnableBufCompilation {
		bufCompiler, err = compiler.NewBufCompiler(compiler.BufConfig{
			BinaryPath:  cfg.Buf.BinaryPath,
			Version:     cfg.Buf.Version,
			Timeout:     cfg.Buf.Timeout,
			MaxMemoryMB: cfg.Buf.MaxMemoryMB,
			WorkDir:     cfg.Buf.WorkDir,
		}, logger)
		if err != nil {
			logger.Warn("Buf compiler initialization failed, compilation will be unavailable",
				slog.String("error", err.Error()),
			)
		}
	}

	// Step 6: Initialize Buf breaking change adapter (optional)
	var bufBreaking *validation.BufBreakingAdapter
	if cfg.Features.EnableBreakingChecks {
		bufBreaking, err = validation.NewBufBreakingAdapter(validation.BufBreakingConfig{
			BinaryPath:      cfg.Buf.BinaryPath,
			Timeout:         cfg.Buf.BreakingTimeout,
			LintTimeout:     cfg.Buf.LintTimeout,
			MaxMemoryMB:     cfg.Buf.MaxMemoryMB,
			WorkDir:         cfg.Buf.WorkDir,
		}, logger)
		if err != nil {
			logger.Warn("Buf breaking adapter initialization failed, breaking checks will be unavailable",
				slog.String("error", err.Error()),
			)
		}
	}

	// Step 7: Create CompatibilityService (domain)
	compatSvc := services.NewCompatibilityService(schemaStore, bufBreaking, logger)

	// Step 8: Create ValidationService (domain)
	validationSvc := services.NewValidationService(schemaStore, bufCompiler, bufBreaking, compatSvc, logger)

	// Step 9: Create RegistryService (domain core)
	registrySvc := services.NewRegistryService(schemaStore, bufCompiler, bufBreaking, nil, logger)

	// Step 10: Create inbound adapters
	grpcHandler := grpc.NewHandler(registrySvc, registrySvc, registrySvc, validationSvc, validationSvc, logger)
	restController := rest.NewController(registrySvc, registrySvc, registrySvc, validationSvc, validationSvc, registrySvc, logger)

	// Step 11: Create server
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
		Config:               cfg,
		RegistryService:      registrySvc,
		CompatibilityService: compatSvc,
		ValidationService:    validationSvc,
		GRPCHandler:          grpcHandler,
		RESTController:       restController,
		SchemaStore:          schemaStore,
		BufCompiler:          bufCompiler,
		BufBreakingAdapter:   bufBreaking,
		OTel:                 otelInst,
		SPIFFE:               spiffeIdentity,
		Server:               srv,
		Logger:               logger,
	}, nil
}

// WireInject is the Wire provider set placeholder. In production, the `wire`
// tool would generate wire_gen.go from this. For this implementation,
// InitializeApp provides manual DI with the same dependency graph.
func WireInject() {}
