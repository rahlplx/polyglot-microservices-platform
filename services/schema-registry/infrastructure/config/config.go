// Package config provides configuration management for the Schema Registry service.
// It reads configuration from environment variables with sensible defaults
// and supports feature flags for gradual rollout of new capabilities.
package config

import (
	"fmt"
	"log/slog"
	"os"
	"strconv"
	"strings"
	"time"
)

// Config holds the complete configuration for the Schema Registry service.
type Config struct {
	// Server configuration
	Server ServerConfig

	// PostgreSQL configuration (for schema persistence)
	Postgres PostgresConfig

	// Buf CLI configuration (for proto compilation and breaking change detection)
	Buf BufCLIConfig

	// OpenTelemetry configuration
	OTel OTelConfig

	// SPIFFE configuration
	SPIFFE SPIFFEConfig

	// Feature flags
	Features FeatureFlags
}

// ServerConfig holds HTTP and gRPC server configuration.
type ServerConfig struct {
	HTTPPort        int           // HTTP server port (default: 8081)
	GRPCPort        int           // gRPC server port (default: 50058)
	MetricsPort     int           // Prometheus metrics port (default: 9090)
	ReadTimeout     time.Duration // HTTP read timeout (default: 30s)
	WriteTimeout    time.Duration // HTTP write timeout (default: 30s)
	IdleTimeout     time.Duration // HTTP idle timeout (default: 120s)
	MaxRequestBody  int64         // Maximum request body size (default: 5MB)
	ShutdownTimeout time.Duration // Graceful shutdown timeout (default: 15s)
	AllowedOrigins  []string      // CORS allowed origins
}

// PostgresConfig holds PostgreSQL connection configuration.
type PostgresConfig struct {
	Host            string        // PostgreSQL host (default: "localhost")
	Port            int           // PostgreSQL port (default: 5432)
	User            string        // Database user (default: "schema_registry")
	Password        string        // Database password
	Database        string        // Database name (default: "schema_registry")
	SSLMode         string        // SSL mode (default: "disable")
	MaxConns        int           // Maximum connections (default: 25)
	MinConns        int           // Minimum connections (default: 5)
	MaxConnIdleTime time.Duration // Maximum idle time (default: 5m)
	MaxConnLifetime time.Duration // Maximum connection lifetime (default: 1h)
}

// BufCLIConfig holds Buf CLI configuration.
type BufCLIConfig struct {
	BinaryPath    string        // Path to the buf binary (default: "buf")
	Version       string        // Required buf version (default: "1.30.0")
	Timeout       time.Duration // Execution timeout (default: 30s)
	BreakingTimeout time.Duration // Breaking change check timeout (default: 60s)
	LintTimeout   time.Duration // Lint check timeout (default: 30s)
	WorkDir       string        // Working directory for temp files
	MaxMemoryMB   int           // Maximum memory per subprocess (default: 512MB)
	MaxConcurrent int           // Maximum concurrent subprocesses (default: 10)
}

// OTelConfig holds OpenTelemetry configuration.
type OTelConfig struct {
	Enabled         bool          // Whether OTel is enabled (default: true)
	Endpoint        string        // OTel Collector endpoint (default: "localhost:4317")
	ServiceName     string        // Service name (default: "schema-registry")
	ServiceVersion  string        // Service version (default: "1.0.0")
	TraceEnabled    bool          // Whether tracing is enabled (default: true)
	MetricsEnabled  bool          // Whether metrics are enabled (default: true)
	SampleRate      float64       // Trace sampling rate 0.0-1.0 (default: 0.1)
	ExportInterval  time.Duration // Metric export interval (default: 15s)
	ExportTimeout   time.Duration // Metric export timeout (default: 5s)
}

// SPIFFEConfig holds SPIFFE/SPIRE workload API configuration.
type SPIFFEConfig struct {
	Enabled         bool          // Whether SPIFFE validation is enabled (default: false)
	TrustDomain     string        // SPIFFE trust domain (default: "example.org")
	WorkloadAPIAddr string        // SPIRE Agent Workload API address
	SVIDTTL         time.Duration // Expected SVID TTL (default: 1h)
}

// FeatureFlags holds feature flag configuration.
type FeatureFlags struct {
	EnableBufCompilation  bool // Enable/disable Buf compilation (default: true)
	EnableBreakingChecks  bool // Enable/disable breaking change detection (default: true)
	EnableEventPublishing bool // Enable/disable event publishing (default: false)
	EnableCaching         bool // Enable/disable schema caching (default: true)
}

// Load reads configuration from environment variables and returns a Config.
// All config values have sensible defaults for local development.
func Load() (*Config, error) {
	cfg := &Config{
		Server: ServerConfig{
			HTTPPort:        getEnvInt("SCHEMA_REGISTRY_HTTP_PORT", 8081),
			GRPCPort:        getEnvInt("SCHEMA_REGISTRY_GRPC_PORT", 50058),
			MetricsPort:     getEnvInt("SCHEMA_REGISTRY_METRICS_PORT", 9090),
			ReadTimeout:     getEnvDuration("SCHEMA_REGISTRY_READ_TIMEOUT", 30*time.Second),
			WriteTimeout:    getEnvDuration("SCHEMA_REGISTRY_WRITE_TIMEOUT", 30*time.Second),
			IdleTimeout:     getEnvDuration("SCHEMA_REGISTRY_IDLE_TIMEOUT", 120*time.Second),
			MaxRequestBody:  getEnvInt64("SCHEMA_REGISTRY_MAX_REQUEST_BODY", 5*1024*1024),
			ShutdownTimeout: getEnvDuration("SCHEMA_REGISTRY_SHUTDOWN_TIMEOUT", 15*time.Second),
			AllowedOrigins:  getEnvStringSlice("SCHEMA_REGISTRY_ALLOWED_ORIGINS", []string{"*"}),
		},
		Postgres: PostgresConfig{
			Host:            getEnvString("SCHEMA_REGISTRY_PG_HOST", "localhost"),
			Port:            getEnvInt("SCHEMA_REGISTRY_PG_PORT", 5432),
			User:            getEnvString("SCHEMA_REGISTRY_PG_USER", "schema_registry"),
			Password:        getEnvString("SCHEMA_REGISTRY_PG_PASSWORD", ""),
			Database:        getEnvString("SCHEMA_REGISTRY_PG_DATABASE", "schema_registry"),
			SSLMode:         getEnvString("SCHEMA_REGISTRY_PG_SSLMODE", "disable"),
			MaxConns:        getEnvInt("SCHEMA_REGISTRY_PG_MAX_CONNS", 25),
			MinConns:        getEnvInt("SCHEMA_REGISTRY_PG_MIN_CONNS", 5),
			MaxConnIdleTime: getEnvDuration("SCHEMA_REGISTRY_PG_MAX_IDLE_TIME", 5*time.Minute),
			MaxConnLifetime: getEnvDuration("SCHEMA_REGISTRY_PG_MAX_LIFETIME", 1*time.Hour),
		},
		Buf: BufCLIConfig{
			BinaryPath:      getEnvString("SCHEMA_REGISTRY_BUF_PATH", "buf"),
			Version:         getEnvString("SCHEMA_REGISTRY_BUF_VERSION", "1.30.0"),
			Timeout:         getEnvDuration("SCHEMA_REGISTRY_BUF_TIMEOUT", 30*time.Second),
			BreakingTimeout: getEnvDuration("SCHEMA_REGISTRY_BUF_BREAKING_TIMEOUT", 60*time.Second),
			LintTimeout:     getEnvDuration("SCHEMA_REGISTRY_BUF_LINT_TIMEOUT", 30*time.Second),
			WorkDir:         getEnvString("SCHEMA_REGISTRY_BUF_WORK_DIR", ""),
			MaxMemoryMB:     getEnvInt("SCHEMA_REGISTRY_BUF_MAX_MEMORY_MB", 512),
			MaxConcurrent:   getEnvInt("SCHEMA_REGISTRY_BUF_MAX_CONCURRENT", 10),
		},
		OTel: OTelConfig{
			Enabled:        getEnvBool("SCHEMA_REGISTRY_OTEL_ENABLED", true),
			Endpoint:       getEnvString("SCHEMA_REGISTRY_OTEL_ENDPOINT", "localhost:4317"),
			ServiceName:    getEnvString("SCHEMA_REGISTRY_OTEL_SERVICE_NAME", "schema-registry"),
			ServiceVersion: getEnvString("SCHEMA_REGISTRY_OTEL_SERVICE_VERSION", "1.0.0"),
			TraceEnabled:   getEnvBool("SCHEMA_REGISTRY_OTEL_TRACE_ENABLED", true),
			MetricsEnabled: getEnvBool("SCHEMA_REGISTRY_OTEL_METRICS_ENABLED", true),
			SampleRate:     getEnvFloat("SCHEMA_REGISTRY_OTEL_SAMPLE_RATE", 0.1),
			ExportInterval: getEnvDuration("SCHEMA_REGISTRY_OTEL_EXPORT_INTERVAL", 15*time.Second),
			ExportTimeout:  getEnvDuration("SCHEMA_REGISTRY_OTEL_EXPORT_TIMEOUT", 5*time.Second),
		},
		SPIFFE: SPIFFEConfig{
			Enabled:         getEnvBool("SCHEMA_REGISTRY_SPIFFE_ENABLED", false),
			TrustDomain:     getEnvString("SCHEMA_REGISTRY_SPIFFE_TRUST_DOMAIN", "example.org"),
			WorkloadAPIAddr: getEnvString("SCHEMA_REGISTRY_SPIFFE_WORKLOAD_API", "unix:///tmp/spire-agent/public/api.sock"),
			SVIDTTL:         getEnvDuration("SCHEMA_REGISTRY_SPIFFE_SVID_TTL", 1*time.Hour),
		},
		Features: FeatureFlags{
			EnableBufCompilation:  getEnvBool("SCHEMA_REGISTRY_FEATURE_BUF_COMPILATION", true),
			EnableBreakingChecks:  getEnvBool("SCHEMA_REGISTRY_FEATURE_BREAKING_CHECKS", true),
			EnableEventPublishing: getEnvBool("SCHEMA_REGISTRY_FEATURE_EVENT_PUBLISHING", false),
			EnableCaching:         getEnvBool("SCHEMA_REGISTRY_FEATURE_CACHING", true),
		},
	}

	if err := cfg.Validate(); err != nil {
		return nil, fmt.Errorf("configuration validation failed: %w", err)
	}

	return cfg, nil
}

// Validate checks the configuration for errors.
func (c *Config) Validate() error {
	if c.Server.HTTPPort < 1 || c.Server.HTTPPort > 65535 {
		return fmt.Errorf("invalid HTTP port: %d", c.Server.HTTPPort)
	}
	if c.Server.GRPCPort < 1 || c.Server.GRPCPort > 65535 {
		return fmt.Errorf("invalid gRPC port: %d", c.Server.GRPCPort)
	}
	if c.Server.HTTPPort == c.Server.GRPCPort {
		return fmt.Errorf("HTTP and gRPC ports must be different, got %d", c.Server.HTTPPort)
	}
	if c.OTel.SampleRate < 0 || c.OTel.SampleRate > 1 {
		return fmt.Errorf("invalid OTel sample rate: %f (must be 0.0-1.0)", c.OTel.SampleRate)
	}
	return nil
}

// LogConfig logs the current configuration at info level (secrets are redacted).
func (c *Config) LogConfig(logger *slog.Logger) {
	logger.Info("schema-registry configuration",
		slog.Int("http_port", c.Server.HTTPPort),
		slog.Int("grpc_port", c.Server.GRPCPort),
		slog.Int("metrics_port", c.Server.MetricsPort),
		slog.String("pg_host", c.Postgres.Host),
		slog.Int("pg_port", c.Postgres.Port),
		slog.String("pg_database", c.Postgres.Database),
		slog.Bool("pg_password_set", c.Postgres.Password != ""),
		slog.String("buf_path", c.Buf.BinaryPath),
		slog.Bool("otel_enabled", c.OTel.Enabled),
		slog.String("otel_endpoint", c.OTel.Endpoint),
		slog.Bool("spiffe_enabled", c.SPIFFE.Enabled),
	)
}

// --- Environment variable helpers ---

func getEnvString(key, defaultVal string) string {
	if val := os.Getenv(key); val != "" {
		return val
	}
	return defaultVal
}

func getEnvInt(key string, defaultVal int) int {
	if val := os.Getenv(key); val != "" {
		if n, err := strconv.Atoi(val); err == nil {
			return n
		}
	}
	return defaultVal
}

func getEnvInt64(key string, defaultVal int64) int64 {
	if val := os.Getenv(key); val != "" {
		if n, err := strconv.ParseInt(val, 10, 64); err == nil {
			return n
		}
	}
	return defaultVal
}

func getEnvBool(key string, defaultVal bool) bool {
	if val := os.Getenv(key); val != "" {
		if b, err := strconv.ParseBool(val); err == nil {
			return b
		}
	}
	return defaultVal
}

func getEnvFloat(key string, defaultVal float64) float64 {
	if val := os.Getenv(key); val != "" {
		if f, err := strconv.ParseFloat(val, 64); err == nil {
			return f
		}
	}
	return defaultVal
}

func getEnvDuration(key string, defaultVal time.Duration) time.Duration {
	if val := os.Getenv(key); val != "" {
		if d, err := time.ParseDuration(val); err == nil {
			return d
		}
	}
	return defaultVal
}

func getEnvStringSlice(key string, defaultVal []string) []string {
	if val := os.Getenv(key); val != "" {
		return strings.Split(val, ",")
	}
	return defaultVal
}
